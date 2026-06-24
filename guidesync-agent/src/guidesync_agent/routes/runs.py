from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse, Response

from guidesync_agent.controllers import run_artifacts
from guidesync_agent.controllers import runs as controller
from guidesync_agent.schemas import (
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProjectRunRequest,
    RunSummary,
)

router = APIRouter(tags=["Runs"])


@router.post("/runs")
async def create_run(request: GuideSyncRunRequest) -> GuideSyncRunResult:
    return await controller.create_run(request)


@router.get("/runs")
async def list_runs(project_id: str | None = Query(default=None)) -> list[RunSummary]:
    return controller.list_runs(project_id=project_id)


@router.get("/projects/{project_id}/runs")
async def list_project_runs(project_id: str) -> list[RunSummary]:
    summaries = controller.list_project_runs(project_id)
    if summaries is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return summaries


@router.post("/projects/{project_id}/runs")
async def create_project_run(
    project_id: str,
    request: ProjectRunRequest,
) -> RunSummary:
    summary = controller.create_project_run(project_id, request)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return summary


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> GuideSyncRunResult:
    result = controller.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return result


@router.get("/runs/{run_id}/artifacts/{filename}")
async def get_run_artifact(
    run_id: str,
    filename: str,
    print_view: bool = Query(default=False, alias="print"),
) -> Response:
    try:
        artifact = run_artifacts.get_run_artifact(run_id, filename, print_view=print_view)
    except run_artifacts.RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except run_artifacts.InvalidArtifactFilenameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except run_artifacts.ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except run_artifacts.ArtifactFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except run_artifacts.ArtifactReadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if isinstance(artifact, run_artifacts.ArtifactRedirect):
        return RedirectResponse(artifact.url)
    return Response(
        content=artifact.body,
        media_type=artifact.media_type,
        headers=artifact.headers,
    )
