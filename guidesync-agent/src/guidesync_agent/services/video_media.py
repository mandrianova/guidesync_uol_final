from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from guidesync_agent.schemas import VideoAudioSegment
from guidesync_agent.settings import VideoPresentationEnvironmentSettings, get_settings

VIDEO_ARTIFACT_NAME = "video-presentation.mp4"


@dataclass(frozen=True)
class VideoProbe:
    duration_seconds: float
    width: int
    height: int
    video_codec: str
    audio_codec: str
    stream_count: int
    sha256: str


def assemble_video(
    slide_paths: dict[str, Path],
    audio_segments: list[VideoAudioSegment],
    output_dir: Path,
    settings: VideoPresentationEnvironmentSettings | None = None,
) -> VideoProbe:
    settings = settings or get_settings().video_presentation
    segment_paths = []
    for index, audio in enumerate(audio_segments, start=1):
        slide = slide_paths.get(f"video-slide-{index:02d}.png")
        audio_path = output_dir / audio.artifact_name
        if slide is None or not slide.is_file() or not audio_path.is_file():
            raise FileNotFoundError(f"Video inputs are incomplete for slide {index}.")
        segment_path = output_dir / f"video-segment-{index:02d}.mp4"
        run_media_command(
            build_slide_segment_command(
                slide,
                audio_path,
                segment_path,
                audio.duration_seconds + settings.slide_padding_seconds,
                settings.slide_padding_seconds,
            ),
            timeout_seconds=settings.ffmpeg_timeout_seconds,
            label=f"FFmpeg slide {index}",
        )
        segment_paths.append(segment_path)
    concat_path = output_dir / "video-segments.txt"
    concat_path.write_text(
        "".join(f"file '{path.name}'\n" for path in segment_paths),
        encoding="utf-8",
    )
    video_path = output_dir / VIDEO_ARTIFACT_NAME
    run_media_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(video_path),
        ],
        timeout_seconds=settings.ffmpeg_timeout_seconds,
        label="FFmpeg concatenation",
    )
    expected_duration = sum(item.duration_seconds for item in audio_segments) + (
        len(audio_segments) * settings.slide_padding_seconds
    )
    return probe_video(
        video_path,
        expected_duration=expected_duration,
        timeout_seconds=settings.ffmpeg_timeout_seconds,
    )


def build_slide_segment_command(
    slide_path: Path,
    audio_path: Path,
    output_path: Path,
    duration_seconds: float,
    padding_seconds: float,
) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-loop",
        "1",
        "-i",
        str(slide_path),
        "-i",
        str(audio_path),
        "-vf",
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-tune",
        "stillimage",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-ac",
        "1",
        "-af",
        f"apad=pad_dur={padding_seconds:.3f}",
        "-t",
        f"{duration_seconds:.3f}",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]


def run_media_command(command: list[str], *, timeout_seconds: int, label: str) -> None:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{label} exceeded {timeout_seconds} seconds.") from exc
    except FileNotFoundError as exc:
        raise RuntimeError(f"{command[0]} is not installed in the worker image.") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-2_000:]
        raise RuntimeError(f"{label} failed: {detail or 'no diagnostic output'}")


def probe_video(
    path: Path,
    *,
    expected_duration: float,
    timeout_seconds: int,
) -> VideoProbe:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise RuntimeError("ffprobe could not validate the generated video.") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {completed.stderr.strip()[-2_000:]}")
    payload = json.loads(completed.stdout)
    streams = payload.get("streams", [])
    video_streams = [item for item in streams if item.get("codec_type") == "video"]
    audio_streams = [item for item in streams if item.get("codec_type") == "audio"]
    if len(video_streams) != 1 or len(audio_streams) != 1:
        raise ValueError("Generated video must contain exactly one video and one audio stream.")
    video = video_streams[0]
    audio = audio_streams[0]
    duration = float(payload["format"]["duration"])
    if video.get("codec_name") != "h264" or audio.get("codec_name") != "aac":
        raise ValueError("Generated video must use H.264 video and AAC audio.")
    if (int(video.get("width", 0)), int(video.get("height", 0))) != (1280, 720):
        raise ValueError("Generated video must be 1280x720.")
    if duration <= 0 or abs(duration - expected_duration) > max(1.0, expected_duration * 0.05):
        raise ValueError(
            f"Generated video duration {duration:.3f}s does not match narration "
            f"timeline {expected_duration:.3f}s."
        )
    body = path.read_bytes()
    if len(body) < 10_000:
        raise ValueError("Generated video is unexpectedly small or empty.")
    return VideoProbe(
        duration_seconds=duration,
        width=1280,
        height=720,
        video_codec="h264",
        audio_codec="aac",
        stream_count=len(streams),
        sha256=hashlib.sha256(body).hexdigest(),
    )
