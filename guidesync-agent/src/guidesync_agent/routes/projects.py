from __future__ import annotations

from fastapi import APIRouter, HTTPException

from guidesync_agent.controllers import projects as controller
from guidesync_agent.schemas import ProjectConfig, ProjectCreate, ProjectProfileSnapshot

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("")
async def list_projects() -> list[ProjectConfig]:
    return controller.list_projects()


@router.post("")
async def create_project(project: ProjectCreate) -> ProjectConfig:
    return controller.create_project(project)


@router.get("/{project_id}")
async def get_project(project_id: str) -> ProjectConfig:
    project = controller.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return project


@router.put("/{project_id}")
async def update_project(project_id: str, project: ProjectCreate) -> ProjectConfig:
    saved = controller.update_project(project_id, project)
    if saved is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return saved


@router.get("/{project_id}/profile")
async def get_project_profile(project_id: str) -> ProjectProfileSnapshot:
    profile = controller.get_latest_project_profile(project_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Project profile not found: {project_id}")
    return profile


@router.get("/{project_id}/profiles")
async def list_project_profiles(project_id: str) -> list[ProjectProfileSnapshot]:
    profiles = controller.get_project_profiles(project_id)
    if profiles is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return profiles


@router.post("/{project_id}/profile")
async def rebuild_project_profile(project_id: str) -> ProjectProfileSnapshot:
    profile = controller.rebuild_project_profile(project_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return profile
