from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from guidesync_agent.agent_runtime.video_presentation import (
    generate_video_presentation_plan,
)
from guidesync_agent.schemas import (
    GuideSyncRunResult,
    ModelRole,
    ProjectWorkflowProgress,
    ProjectWorkflowRequestedBy,
    ProjectWorkflowStage,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProjectWorkflowTaskStatus,
    ProviderConfig,
    PublicationReport,
    VideoAudioSegment,
    VideoPresentationManifest,
    VideoPresentationPlan,
    VideoPresentationPolicy,
    VideoPresentationStatus,
    VideoPresentationSummary,
    VideoPresentationWorkflowInput,
    VideoPresentationWorkflowResult,
    VideoSlideArtifact,
)
from guidesync_agent.services.model_roles import provider_config_for_role
from guidesync_agent.settings import get_settings
from guidesync_agent.storage import (
    create_project_workflow_store,
    create_run_store,
    project_id_from_run_id,
)

from .media import VideoProbe, assemble_video
from .presentation_artifacts import (
    VideoPublicationTarget,
    persist_final_video_artifacts,
    persist_plan_artifacts,
    restore_audio_artifacts,
    restore_slide_artifacts,
    upload_video_artifacts,
    video_publication_artifact_names,
)
from .rendering import render_video_slides, slide_artifact_name, validate_slide_png
from .tts import TtsBatchResult, generate_tts_segments


@dataclass(frozen=True)
class VideoGenerationOutcome:
    tts: TtsBatchResult
    probe: VideoProbe
    manifest: VideoPresentationManifest


def enqueue_video_presentation(
    run_id: str,
    *,
    regenerate: bool = False,
) -> VideoPresentationSummary:
    run_store = create_run_store()
    run = run_store.get(run_id)
    if run is None:
        raise KeyError(f"Run not found: {run_id}")
    if run_store.get_publication_report(run_id) is None:
        raise ValueError("Video generation requires a ready publication report.")
    project_id = project_id_from_run_id(run_id)
    if project_id is None:
        raise ValueError("Video generation requires a saved project run.")
    current = run.video_presentation
    has_video = current.video_artifact_name is not None
    if regenerate and not has_video:
        raise ValueError("No completed video is available to regenerate.")
    if not regenerate and current.status is VideoPresentationStatus.COMPLETED and has_video:
        raise ValueError("A video already exists. Use regeneration to replace it.")

    candidate = ProjectWorkflowTask(
        project_id=project_id,
        kind=ProjectWorkflowTaskKind.VIDEO_PRESENTATION,
        dedupe_key=f"video_presentation:{run_id}",
        requested_by=ProjectWorkflowRequestedBy.USER,
        reason=(
            "regenerate_release_notes_video"
            if regenerate
            else "generate_release_notes_video"
        ),
        input=VideoPresentationWorkflowInput(run_id=run_id, regenerate=regenerate),
        max_attempts=2,
    )
    task = create_project_workflow_store().enqueue(candidate)
    if task.id != candidate.id:
        latest = run_store.get(run_id)
        return latest.video_presentation if latest is not None else current
    queued = current.model_copy(
        update={
            "policy": VideoPresentationPolicy.OPTIONAL,
            "status": VideoPresentationStatus.QUEUED,
            "workflow_task_id": task.id,
            "warnings": [],
            "error_message": None,
        }
    )
    update_run_video_state(run_id, queued)
    return queued


async def execute_video_presentation(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    task_input = VideoPresentationWorkflowInput.model_validate(task.input)
    run_store = create_run_store()
    run = run_store.get(task_input.run_id)
    if run is None:
        raise ValueError(f"Workflow run not found: {task_input.run_id}")
    report = run_store.get_publication_report(task_input.run_id)
    if report is None:
        raise ValueError("Video presentation requires a persisted publication report.")
    existing_result = existing_video_result(task)
    if existing_result and existing_result.presentation.status is VideoPresentationStatus.COMPLETED:
        return task

    running_summary = run.video_presentation.model_copy(
        update={
            "policy": VideoPresentationPolicy.OPTIONAL,
            "status": VideoPresentationStatus.RUNNING,
            "workflow_task_id": task.id,
            "warnings": [],
            "error_message": None,
        }
    )
    task = save_video_checkpoint(
        task, existing_result.plan if existing_result else None, running_summary
    )
    update_run_video_state(run.run_id, running_summary)

    plan = await prepare_video_plan(task, run, report, existing_result)
    task = save_video_checkpoint(task, plan, running_summary)
    ensure_task_active(task.id)
    outcome = await produce_video_artifacts_without_blocking(
        task,
        run,
        report,
        plan,
        running_summary,
    )

    completed_summary = VideoPresentationSummary(
        policy=VideoPresentationPolicy.OPTIONAL,
        status=VideoPresentationStatus.COMPLETED,
        workflow_task_id=task.id,
        video_artifact_name=outcome.manifest.video_artifact_name,
        manifest_artifact_name=video_publication_artifact_names(task.id).manifest,
        transcript_artifact_name=outcome.manifest.transcript_artifact_name,
        duration_seconds=outcome.probe.duration_seconds,
        tts_backend="sherpa-onnx",
        tts_model=outcome.tts.model,
        tts_voice=outcome.tts.voice,
    )
    update_run_video_state(run.run_id, completed_summary)
    update_video_progress(task, "Video presentation completed", 4, 4)
    return task.model_copy(
        update={
            "result": VideoPresentationWorkflowResult(
                plan=plan,
                presentation=completed_summary,
                slides=outcome.manifest.slides,
                audio_segments=outcome.manifest.audio_segments,
            )
        }
    )


async def prepare_video_plan(
    task: ProjectWorkflowTask,
    run: GuideSyncRunResult,
    report: PublicationReport,
    existing_result: VideoPresentationWorkflowResult | None,
) -> VideoPresentationPlan:
    if existing_result and existing_result.plan is not None:
        return existing_result.plan
    return await generate_video_presentation_plan(
        report,
        video_plan_provider(run.request.provider, task),
        project_id=task.project_id,
        run_id=run.run_id,
        workflow_task_id=task.id,
    )


def produce_video_artifacts(
    task: ProjectWorkflowTask,
    run: GuideSyncRunResult,
    report: PublicationReport,
    plan: VideoPresentationPlan,
    running_summary: VideoPresentationSummary,
) -> VideoGenerationOutcome:
    with TemporaryDirectory(prefix=f"guidesync-video-{run.run_id}-") as temp_dir:
        output_dir = Path(temp_dir)
        target = VideoPublicationTarget(
            output_dir=output_dir,
            names=video_publication_artifact_names(task.id),
        )
        run = persist_plan_artifacts(run.run_id, plan, target)
        run, slide_paths = prepare_slide_artifacts(task, run, report, plan, output_dir)
        run, tts = prepare_audio_artifacts(
            task,
            run,
            plan,
            output_dir,
            running_summary,
        )
        update_video_progress(task, "Assembling and validating MP4", 3, 4)
        probe = assemble_video(slide_paths, tts.segments, output_dir)
        manifest = persist_final_video_artifacts(
            plan,
            slide_paths,
            tts,
            probe,
            target,
        )
    return VideoGenerationOutcome(tts=tts, probe=probe, manifest=manifest)


async def produce_video_artifacts_without_blocking(
    task: ProjectWorkflowTask,
    run: GuideSyncRunResult,
    report: PublicationReport,
    plan: VideoPresentationPlan,
    running_summary: VideoPresentationSummary,
) -> VideoGenerationOutcome:
    return await asyncio.to_thread(
        produce_video_artifacts,
        task,
        run,
        report,
        plan,
        running_summary,
    )


def prepare_slide_artifacts(
    task: ProjectWorkflowTask,
    run: GuideSyncRunResult,
    report: PublicationReport,
    plan: VideoPresentationPlan,
    output_dir: Path,
) -> tuple[GuideSyncRunResult, dict[str, Path]]:
    update_video_progress(task, "Rendering validated 16:9 slides", 1, 4)
    checkpoint = existing_video_result(task)
    slide_paths = restore_slide_artifacts(
        run,
        plan,
        output_dir,
        checkpoint.slides if checkpoint else [],
    )
    if len(slide_paths) != len(plan.slides):
        slide_paths = render_video_slides(plan, report, output_dir)
        run = upload_video_artifacts(run.run_id, slide_paths)
    slides = [
        validate_slide_png(slide_paths[slide_artifact_name(slide.position)])
        for slide in plan.slides
    ]
    save_video_checkpoint(task, plan, existing_presentation(task), slides=slides)
    ensure_task_active(task.id)
    return run, slide_paths


def prepare_audio_artifacts(
    task: ProjectWorkflowTask,
    run: GuideSyncRunResult,
    plan: VideoPresentationPlan,
    output_dir: Path,
    running_summary: VideoPresentationSummary,
) -> tuple[GuideSyncRunResult, TtsBatchResult]:
    update_video_progress(task, "Generating bounded narration audio", 2, 4)
    checkpoint = existing_video_result(task)
    tts = restore_audio_artifacts(
        run,
        plan,
        output_dir,
        checkpoint.audio_segments if checkpoint else [],
    )
    if tts is None:
        tts = generate_tts_segments(plan, output_dir)
        run = upload_video_artifacts(
            run.run_id,
            {item.artifact_name: output_dir / item.artifact_name for item in tts.segments},
        )
    validate_presentation_duration(tts)
    save_video_checkpoint(
        task,
        plan,
        tts_running_summary(running_summary, tts),
        audio_segments=tts.segments,
    )
    ensure_task_active(task.id)
    return run, tts


def validate_presentation_duration(tts: TtsBatchResult) -> None:
    settings = get_settings().video_presentation
    duration = sum(segment.duration_seconds for segment in tts.segments) + (
        len(tts.segments) * settings.slide_padding_seconds
    )
    if duration > settings.max_duration_seconds:
        raise ValueError(
            f"Video narration timeline {duration:.1f}s exceeds the configured "
            f"{settings.max_duration_seconds}s maximum."
        )


def tts_running_summary(
    summary: VideoPresentationSummary,
    tts: TtsBatchResult,
) -> VideoPresentationSummary:
    return summary.model_copy(
        update={
            "tts_backend": "sherpa-onnx",
            "tts_model": tts.model,
            "tts_voice": tts.voice,
        }
    )


def video_plan_provider(fallback: ProviderConfig, task: ProjectWorkflowTask) -> ProviderConfig:
    config = provider_config_for_role(ModelRole.ORCHESTRATOR, fallback=fallback)
    return config.model_copy(
        update={
            "metadata": {
                **config.metadata,
                "project_id": task.project_id,
                "run_id": getattr(task.input, "run_id", None),
                "workflow_task_id": task.id,
            }
        }
    )


def existing_video_result(task: ProjectWorkflowTask) -> VideoPresentationWorkflowResult | None:
    if task.result is None:
        return None
    return VideoPresentationWorkflowResult.model_validate(task.result)


def existing_presentation(task: ProjectWorkflowTask) -> VideoPresentationSummary:
    existing = existing_video_result(task)
    if existing is None:
        raise ValueError("Video presentation checkpoint is missing.")
    return existing.presentation


def save_video_checkpoint(
    task: ProjectWorkflowTask,
    plan: VideoPresentationPlan | None,
    presentation: VideoPresentationSummary,
    *,
    slides: list[VideoSlideArtifact] | None = None,
    audio_segments: list[VideoAudioSegment] | None = None,
) -> ProjectWorkflowTask:
    store = create_project_workflow_store()
    latest = store.get(task.id) or task
    existing = existing_video_result(latest)
    checkpoint = latest.model_copy(
        update={
            "result": VideoPresentationWorkflowResult(
                plan=plan,
                presentation=presentation,
                slides=slides if slides is not None else (existing.slides if existing else []),
                audio_segments=(
                    audio_segments
                    if audio_segments is not None
                    else (existing.audio_segments if existing else [])
                ),
            )
        }
    )
    return store.save(checkpoint)


def update_video_progress(
    task: ProjectWorkflowTask,
    message: str,
    completed_items: int,
    total_items: int,
) -> None:
    if not task.lease_token:
        return
    create_project_workflow_store().heartbeat(
        task.id,
        task.lease_token,
        ProjectWorkflowProgress(
            stage=ProjectWorkflowStage.GENERATING_PRESENTATION,
            message=message,
            completed_items=completed_items,
            total_items=total_items,
        ),
    )


def ensure_task_active(task_id: str) -> None:
    task = create_project_workflow_store().get(task_id)
    if task is None or task.status is not ProjectWorkflowTaskStatus.RUNNING:
        raise RuntimeError("Video presentation task was cancelled while processing.")


def update_run_video_state(run_id: str, summary: VideoPresentationSummary) -> None:
    store = create_run_store()
    run = store.get(run_id)
    if run is None:
        return
    updated = run.model_copy(update={"video_presentation": summary})
    store.save(updated)
    store.record_run_event(
        run_id,
        run.status,
        f"Video presentation stage changed to {summary.status.value}.",
        "video_presentation",
    )


def fail_video_presentation(task: ProjectWorkflowTask, *, retrying: bool) -> None:
    if task.kind is not ProjectWorkflowTaskKind.VIDEO_PRESENTATION:
        return
    task_input = VideoPresentationWorkflowInput.model_validate(task.input)
    run = create_run_store().get(task_input.run_id)
    if run is None:
        return
    public_message = "Video presentation generation failed. See internal workflow diagnostics."
    update_run_video_state(
        run.run_id,
        run.video_presentation.model_copy(
            update={
                "policy": VideoPresentationPolicy.OPTIONAL,
                "status": (
                    VideoPresentationStatus.RETRYING
                    if retrying
                    else VideoPresentationStatus.FAILED
                ),
                "workflow_task_id": task.id,
                "warnings": [public_message] if retrying else [],
                "error_message": None if retrying else public_message,
            },
        ),
    )
