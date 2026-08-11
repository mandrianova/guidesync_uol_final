from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

from guidesync_agent.schemas import VideoAudioSegment, VideoPresentationPlan
from guidesync_agent.settings import VideoPresentationEnvironmentSettings, get_settings


@dataclass(frozen=True)
class TtsBatchResult:
    backend_version: str
    model: str
    voice: str
    voice_id: int
    speed: float
    segments: list[VideoAudioSegment]


def generate_tts_segments(
    plan: VideoPresentationPlan,
    output_dir: Path,
    settings: VideoPresentationEnvironmentSettings | None = None,
) -> TtsBatchResult:
    settings = settings or get_settings().video_presentation
    validate_model_directory(settings.model_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    request_path = output_dir / "video-tts-request.json"
    result_path = output_dir / "video-tts-result.json"
    request_path.write_text(
        json.dumps(
            {
                "model_dir": str(settings.model_dir),
                "model_id": settings.model_id,
                "voice": settings.voice,
                "voice_id": settings.voice_id,
                "speed": settings.speed,
                "num_threads": settings.num_threads,
                "slides": [
                    {
                        "slide_id": slide.id,
                        "artifact_name": audio_artifact_name(slide.position),
                        "narration": slide.narration,
                    }
                    for slide in plan.slides
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-m",
        "guidesync_agent.video_tts_cli",
        "--request",
        str(request_path),
        "--output-dir",
        str(output_dir),
        "--result",
        str(result_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.tts_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"sherpa-onnx TTS exceeded {settings.tts_timeout_seconds} seconds."
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-2_000:]
        raise RuntimeError(f"sherpa-onnx TTS failed: {detail or 'no diagnostic output'}")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    segments = [
        validate_audio_segment(output_dir / item["artifact_name"], item["slide_id"])
        for item in payload["segments"]
    ]
    return TtsBatchResult(
        backend_version=str(payload["backend_version"]),
        model=str(payload["model"]),
        voice=str(payload["voice"]),
        voice_id=int(payload["voice_id"]),
        speed=float(payload["speed"]),
        segments=segments,
    )


def validate_model_directory(model_dir: Path) -> None:
    required = ["model.onnx", "voices.bin", "tokens.txt", "espeak-ng-data"]
    missing = [name for name in required if not (model_dir / name).exists()]
    if missing:
        raise FileNotFoundError(
            f"Kokoro TTS model is incomplete at {model_dir}; missing: {', '.join(missing)}. "
            "Run the Compose tts-model-download profile first."
        )


def audio_artifact_name(position: int) -> str:
    return f"video-narration-{position:02d}.wav"


def validate_audio_segment(path: Path, slide_id: str) -> VideoAudioSegment:
    if not path.is_file() or path.stat().st_size <= 44:
        raise ValueError(f"Narration audio is empty: {path.name}")
    with wave.open(str(path), "rb") as audio:
        frame_count = audio.getnframes()
        sample_rate = audio.getframerate()
        channels = audio.getnchannels()
    if frame_count <= 0 or sample_rate <= 0 or channels != 1:
        raise ValueError(f"Narration audio has an invalid WAV format: {path.name}")
    return VideoAudioSegment(
        slide_id=slide_id,
        artifact_name=path.name,
        duration_seconds=frame_count / sample_rate,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
