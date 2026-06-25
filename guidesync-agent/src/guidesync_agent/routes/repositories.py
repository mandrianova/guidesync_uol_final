from __future__ import annotations

from fastapi import APIRouter, HTTPException

from guidesync_agent.controllers import repositories as controller
from guidesync_agent.schemas import BranchListResponse, ProjectRepository

router = APIRouter(prefix="/projects/{project_id}/repositories", tags=["Repositories"])


@router.post("/{repository_id}/sync")
async def sync_repository(project_id: str, repository_id: str) -> ProjectRepository:
    try:
        return controller.sync_repository(project_id, repository_id)
    except controller.RepositoryProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except controller.RepositoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{repository_id}/status")
async def repository_status(project_id: str, repository_id: str) -> ProjectRepository:
    try:
        return controller.repository_status(project_id, repository_id)
    except controller.RepositoryProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except controller.RepositoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{repository_id}/branches")
async def list_branches(project_id: str, repository_id: str) -> BranchListResponse:
    try:
        return controller.list_branches(project_id, repository_id)
    except controller.RepositoryProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except controller.RepositoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
