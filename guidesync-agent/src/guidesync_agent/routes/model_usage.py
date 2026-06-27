from __future__ import annotations

from fastapi import APIRouter, Query

from guidesync_agent.controllers import model_usage as controller
from guidesync_agent.schemas import (
    ModelCallLedgerEntry,
    RunTokenUsageSummary,
    WorkflowTaskTokenUsageSummary,
)

router = APIRouter(prefix="/runs/{run_id}/model-usage", tags=["Model usage"])
workflow_task_router = APIRouter(
    prefix="/workflow-tasks/{workflow_task_id}/model-usage",
    tags=["Model usage"],
)


@router.get("")
async def list_run_model_usage(
    run_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ModelCallLedgerEntry]:
    return controller.list_run_model_usage(run_id, limit=limit, offset=offset)


@router.get("/summary")
async def summarize_run_model_usage(run_id: str) -> RunTokenUsageSummary:
    return controller.summarize_run_model_usage(run_id)


@workflow_task_router.get("/summary")
async def summarize_workflow_task_model_usage(
    workflow_task_id: str,
) -> WorkflowTaskTokenUsageSummary:
    return controller.summarize_workflow_task_model_usage(workflow_task_id)
