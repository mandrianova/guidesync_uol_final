from __future__ import annotations

from guidesync_agent.pipeline import run_guidesync
from guidesync_agent.schemas import (
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProjectRunRequest,
    ProjectWorkflowPlan,
    RunCancellationResult,
    RunSummary,
    VideoPresentationCommand,
    VideoPresentationSummary,
)
from guidesync_agent.services.video.presentation import enqueue_video_presentation
from guidesync_agent.services.workflows.planner import ProjectWorkflowPlanner
from guidesync_agent.storage import (
    create_project_store,
    create_project_workflow_store,
    create_run_store,
)


async def create_run(request: GuideSyncRunRequest) -> GuideSyncRunResult:
    return await run_guidesync(request)


def list_runs(project_id: str | None = None) -> list[RunSummary]:
    return create_run_store().list_runs(project_id=project_id)


def list_project_runs(project_id: str) -> list[RunSummary] | None:
    if create_project_store().get(project_id) is None:
        return None
    return create_run_store().list_runs(project_id=project_id)


def create_project_run(project_id: str, request: ProjectRunRequest) -> RunSummary | None:
    project = create_project_store().get(project_id)
    if project is None:
        return None
    plan = ProjectWorkflowPlanner().enqueue_change_analysis_pipeline(project.id, request)
    return plan.run if plan else None


def get_run(run_id: str) -> GuideSyncRunResult | None:
    return create_run_store().get(run_id)


def retry_run(run_id: str) -> ProjectWorkflowPlan:
    return ProjectWorkflowPlanner().retry_change_analysis_run(run_id)


def get_video_presentation(run_id: str) -> VideoPresentationSummary | None:
    run = create_run_store().get(run_id)
    return run.video_presentation if run is not None else None


def generate_video_presentation(
    run_id: str,
    command: VideoPresentationCommand,
) -> VideoPresentationSummary:
    return enqueue_video_presentation(run_id, regenerate=command.regenerate)


def cancel_run(run_id: str) -> RunCancellationResult:
    return create_project_workflow_store().cancel_run(
        run_id,
        reason="Cancelled at user request.",
    )
