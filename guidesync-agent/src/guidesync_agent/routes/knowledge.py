from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from guidesync_agent.controllers import knowledge as controller
from guidesync_agent.schemas import (
    KnowledgeContextPack,
    KnowledgeContextPackRequest,
    KnowledgeDocumentRefs,
    KnowledgeIndexRequest,
    KnowledgeIndexRun,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    KnowledgeTag,
    ProjectKnowledgeIndexRequest,
)

router = APIRouter(tags=["Knowledge"])


@router.post("/knowledge/index-runs")
async def create_index_run(request: KnowledgeIndexRequest) -> KnowledgeIndexRun:
    try:
        return controller.create_index_run(request)
    except controller.KnowledgeProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except controller.KnowledgeIndexRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/knowledge/index-runs")
async def create_project_index_run(
    project_id: str,
    request: ProjectKnowledgeIndexRequest | None = None,
) -> KnowledgeIndexRun:
    try:
        project_request = request or ProjectKnowledgeIndexRequest()
        return controller.create_project_index_run(project_id, project_request)
    except controller.KnowledgeProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except controller.KnowledgeIndexRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/knowledge/index-runs")
async def list_index_runs(
    project_id: str | None = Query(default=None),
) -> list[KnowledgeIndexRun]:
    return controller.list_index_runs(project_id=project_id)


@router.get("/projects/{project_id}/knowledge/index-runs")
async def list_project_index_runs(project_id: str) -> list[KnowledgeIndexRun]:
    try:
        return controller.list_project_index_runs(project_id)
    except controller.KnowledgeProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/knowledge/index-runs/{run_id}")
async def get_index_run(run_id: str) -> KnowledgeIndexRun:
    run = controller.get_index_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Knowledge index run not found: {run_id}")
    return run


@router.post("/knowledge/search")
async def search(request: KnowledgeSearchRequest) -> list[KnowledgeSearchResult]:
    return controller.search(request)


@router.post("/projects/{project_id}/knowledge/search")
async def project_search(
    project_id: str,
    request: KnowledgeSearchRequest,
) -> list[KnowledgeSearchResult]:
    try:
        return controller.project_search(project_id, request)
    except controller.KnowledgeProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/knowledge/documents")
async def document_refs(project_id: str) -> KnowledgeDocumentRefs:
    try:
        return controller.document_refs(project_id)
    except controller.KnowledgeProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/knowledge/tags")
async def tag_cloud(project_id: str) -> list[KnowledgeTag]:
    try:
        return controller.tag_cloud(project_id)
    except controller.KnowledgeProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/knowledge/context-pack")
async def context_pack(request: KnowledgeContextPackRequest) -> KnowledgeContextPack:
    return controller.context_pack(request)
