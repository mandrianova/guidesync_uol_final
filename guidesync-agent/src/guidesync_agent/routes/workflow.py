from __future__ import annotations

from fastapi import APIRouter, HTTPException

from guidesync_agent.controllers import workflow as controller
from guidesync_agent.schemas import (
    ProjectPipelineState,
    ProjectRunRequest,
    ProjectWorkflowPlan,
    ProjectWorkflowTask,
)

router = APIRouter(prefix="/projects/{project_id}/workflow", tags=["Workflow"])


@router.get("/tasks")
async def list_project_workflow_tasks(project_id: str) -> list[ProjectWorkflowTask]:
    tasks = controller.list_project_workflow_tasks(project_id)
    if tasks is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return tasks


@router.get("/state")
async def project_pipeline_state(project_id: str) -> ProjectPipelineState:
    state = controller.project_pipeline_state(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return state


@router.post("/profile")
async def enqueue_profile_rebuild(project_id: str) -> ProjectWorkflowPlan:
    plan = controller.enqueue_profile_rebuild(project_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return plan


@router.post("/knowledge")
async def enqueue_initial_knowledge_base(project_id: str) -> ProjectWorkflowPlan:
    plan = controller.enqueue_initial_knowledge_base(project_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return plan


@router.post("/run-analysis")
async def enqueue_change_analysis_pipeline(
    project_id: str,
    request: ProjectRunRequest,
) -> ProjectWorkflowPlan:
    plan = controller.enqueue_change_analysis_pipeline(project_id, request)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return plan
