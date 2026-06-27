from __future__ import annotations

from guidesync_agent.schemas import (
    ModelCallLedgerEntry,
    RunTokenUsageSummary,
    WorkflowTaskTokenUsageSummary,
)
from guidesync_agent.storage import create_model_usage_store


def list_run_model_usage(
    run_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[ModelCallLedgerEntry]:
    return create_model_usage_store().list_for_run(run_id, limit=limit, offset=offset)


def summarize_run_model_usage(run_id: str) -> RunTokenUsageSummary:
    return create_model_usage_store().summarize_run(run_id)


def summarize_workflow_task_model_usage(
    workflow_task_id: str,
) -> WorkflowTaskTokenUsageSummary:
    return create_model_usage_store().summarize_workflow_task(workflow_task_id)
