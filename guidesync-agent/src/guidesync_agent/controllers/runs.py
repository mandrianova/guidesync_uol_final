from __future__ import annotations

from guidesync_agent.pipeline import run_guidesync
from guidesync_agent.schemas import (
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProjectRunRequest,
    RunSummary,
)
from guidesync_agent.services import ReportRunService
from guidesync_agent.storage import create_project_store, create_run_store


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
    return ReportRunService(create_run_store()).create_project_run(
        project=project,
        request=request,
    )


def get_run(run_id: str) -> GuideSyncRunResult | None:
    return create_run_store().get(run_id)

