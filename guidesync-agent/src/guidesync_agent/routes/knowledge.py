from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from guidesync_agent.controllers import knowledge as controller
from guidesync_agent.schemas import (
    KnowledgeContextPack,
    KnowledgeContextPackRequest,
    KnowledgeIndexRequest,
    KnowledgeIndexRun,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)

router = APIRouter(prefix="/knowledge", tags=["Knowledge"])


@router.post("/index-runs")
async def create_index_run(request: KnowledgeIndexRequest) -> KnowledgeIndexRun:
    try:
        return controller.create_index_run(request)
    except controller.KnowledgeProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except controller.KnowledgeIndexRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/index-runs")
async def list_index_runs(
    project_id: str | None = Query(default=None),
) -> list[KnowledgeIndexRun]:
    return controller.list_index_runs(project_id=project_id)


@router.get("/index-runs/{run_id}")
async def get_index_run(run_id: str) -> KnowledgeIndexRun:
    run = controller.get_index_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Knowledge index run not found: {run_id}")
    return run


@router.post("/search")
async def search(request: KnowledgeSearchRequest) -> list[KnowledgeSearchResult]:
    return controller.search(request)


@router.post("/context-pack")
async def context_pack(request: KnowledgeContextPackRequest) -> KnowledgeContextPack:
    return controller.context_pack(request)
