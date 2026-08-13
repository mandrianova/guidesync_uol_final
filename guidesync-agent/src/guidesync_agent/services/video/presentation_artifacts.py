from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from guidesync_agent.config import artifact_storage_config
from guidesync_agent.reports import read_artifact, write_s3_existing_artifacts
from guidesync_agent.schemas import (
    GuideSyncRunResult,
    VideoAudioSegment,
    VideoPresentationManifest,
    VideoPresentationPlan,
    VideoSlideArtifact,
)
from guidesync_agent.settings import get_settings
from guidesync_agent.storage import create_run_store

from .media import VIDEO_ARTIFACT_NAME, VideoProbe
from .rendering import slide_artifact_name, validate_slide_png
from .tts import TtsBatchResult, audio_artifact_name, validate_audio_segment

PLAN_ARTIFACT_NAME = "video-presentation-plan.json"
MANIFEST_ARTIFACT_NAME = "video-presentation-manifest.json"
TRANSCRIPT_ARTIFACT_NAME = "video-presentation-transcript.txt"


@dataclass(frozen=True)
class VideoPublicationArtifactNames:
    plan: str
    manifest: str
    transcript: str
    video: str


@dataclass(frozen=True)
class VideoPublicationTarget:
    output_dir: Path
    names: VideoPublicationArtifactNames


def video_publication_artifact_names(
    workflow_task_id: str | None = None,
) -> VideoPublicationArtifactNames:
    suffix = f"-{workflow_task_id}" if workflow_task_id else ""
    return VideoPublicationArtifactNames(
        plan=f"video-presentation-plan{suffix}.json",
        manifest=f"video-presentation-manifest{suffix}.json",
        transcript=f"video-presentation-transcript{suffix}.txt",
        video=f"video-presentation{suffix}.mp4",
    )


def persist_plan_artifacts(
    run_id: str,
    plan: VideoPresentationPlan,
    target: VideoPublicationTarget,
) -> GuideSyncRunResult:
    write_plan_and_transcript(plan, target.output_dir)
    return upload_video_artifacts(
        run_id,
        {
            target.names.plan: target.output_dir / PLAN_ARTIFACT_NAME,
            target.names.transcript: target.output_dir / TRANSCRIPT_ARTIFACT_NAME,
        },
    )


def persist_final_video_artifacts(
    plan: VideoPresentationPlan,
    slide_paths: dict[str, Path],
    tts: TtsBatchResult,
    probe: VideoProbe,
    target: VideoPublicationTarget,
) -> VideoPresentationManifest:
    manifest = build_video_manifest(
        plan,
        slide_paths,
        tts,
        probe,
        names=target.names,
    )
    (target.output_dir / MANIFEST_ARTIFACT_NAME).write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    upload_video_artifacts(
        plan.run_id,
        {
            target.names.video: target.output_dir / VIDEO_ARTIFACT_NAME,
            target.names.manifest: target.output_dir / MANIFEST_ARTIFACT_NAME,
        },
    )
    return manifest


def write_plan_and_transcript(plan: VideoPresentationPlan, output_dir: Path) -> None:
    (output_dir / PLAN_ARTIFACT_NAME).write_text(
        plan.model_dump_json(indent=2),
        encoding="utf-8",
    )
    transcript = "\n\n".join(
        f"{slide.position}. {slide.headline}\n{slide.narration}" for slide in plan.slides
    )
    (output_dir / TRANSCRIPT_ARTIFACT_NAME).write_text(transcript + "\n", encoding="utf-8")


def upload_video_artifacts(
    run_id: str,
    local_artifacts: dict[str, Path],
) -> GuideSyncRunResult:
    run_store = create_run_store()
    run = run_store.get(run_id)
    if run is None:
        raise ValueError(f"Workflow run not found: {run_id}")
    uploaded = write_s3_existing_artifacts(
        run,
        {name: str(path) for name, path in local_artifacts.items()},
        artifact_storage_config(),
    )
    updated = run.model_copy(update={"artifacts": {**run.artifacts, **uploaded}})
    run_store.save(updated)
    return updated


def restore_slide_artifacts(
    run: GuideSyncRunResult,
    plan: VideoPresentationPlan,
    output_dir: Path,
    expected: list[VideoSlideArtifact],
) -> dict[str, Path]:
    if not expected:
        return {}
    names = [slide_artifact_name(slide.position) for slide in plan.slides]
    restored = restore_registered_artifacts(run, names, output_dir)
    expected_by_name = {item.artifact_name: item for item in expected}
    if set(restored) != set(names) or set(expected_by_name) != set(names):
        return {}
    try:
        for name, path in restored.items():
            actual = validate_slide_png(path)
            checkpoint = expected_by_name[name]
            if actual.sha256 != checkpoint.sha256 or actual.slide_id != checkpoint.slide_id:
                return {}
    except ValueError:
        return {}
    return restored


def restore_audio_artifacts(
    run: GuideSyncRunResult,
    plan: VideoPresentationPlan,
    output_dir: Path,
    expected: list[VideoAudioSegment],
) -> TtsBatchResult | None:
    names = [audio_artifact_name(slide.position) for slide in plan.slides]
    expected_by_name = {item.artifact_name: item for item in expected}
    if not expected or set(expected_by_name) != set(names):
        return None
    restored = restore_registered_artifacts(run, names, output_dir)
    if len(restored) != len(names):
        return None
    try:
        segments = [
            validate_audio_segment(output_dir / name, slide.id)
            for name, slide in zip(names, plan.slides, strict=True)
        ]
    except (ValueError, OSError):
        return None
    if any(
        item.sha256 != expected_by_name[item.artifact_name].sha256
        or item.slide_id != expected_by_name[item.artifact_name].slide_id
        for item in segments
    ):
        return None
    settings = get_settings().video_presentation
    return TtsBatchResult(
        backend_version=version("sherpa-onnx"),
        model=settings.model_id,
        voice=settings.voice,
        voice_id=settings.voice_id,
        speed=settings.speed,
        segments=segments,
    )


def restore_registered_artifacts(
    run: GuideSyncRunResult,
    names: list[str],
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    restored: dict[str, Path] = {}
    for name in names:
        uri = run.artifacts.get(name)
        if not uri:
            continue
        try:
            body = read_artifact(uri).body
        except (FileNotFoundError, ValueError):
            continue
        path = output_dir / name
        path.write_bytes(body)
        restored[name] = path
    return restored


def build_video_manifest(
    plan: VideoPresentationPlan,
    slide_paths: dict[str, Path],
    tts: TtsBatchResult,
    probe: VideoProbe,
    *,
    names: VideoPublicationArtifactNames | None = None,
) -> VideoPresentationManifest:
    names = names or video_publication_artifact_names()
    slides = [
        validate_slide_png(slide_paths[slide_artifact_name(item.position)]) for item in plan.slides
    ]
    return VideoPresentationManifest(
        run_id=plan.run_id,
        plan_artifact_name=names.plan,
        transcript_artifact_name=names.transcript,
        video_artifact_name=names.video,
        slides=slides,
        audio_segments=tts.segments,
        tts_backend_version=tts.backend_version,
        tts_model=tts.model,
        tts_voice=tts.voice,
        tts_voice_id=tts.voice_id,
        tts_speed=tts.speed,
        duration_seconds=probe.duration_seconds,
        video_sha256=probe.sha256,
        video_codec=probe.video_codec,
        audio_codec=probe.audio_codec,
    )
