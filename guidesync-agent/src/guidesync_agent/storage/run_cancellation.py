from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from guidesync_agent.models import (
    llm_conversations_table,
    project_workflow_tasks_table,
    report_runs_table,
    run_events_table,
)
from guidesync_agent.schemas import (
    LLMConversationStatus,
    ProjectWorkflowProgress,
    ProjectWorkflowStage,
    ProjectWorkflowTask,
    ProjectWorkflowTaskStatus,
    RunCancellationResult,
    ValidationFinding,
)

from .serialization import run_result_from_snapshot, workflow_values


def cancel_run_transaction(
    connection: Connection,
    tasks: list[ProjectWorkflowTask],
    *,
    run_id: str,
    reason: str,
) -> RunCancellationResult:
    now = datetime.now(UTC)
    run_row = connection.execute(
        select(report_runs_table.c.result_snapshot).where(report_runs_table.c.id == run_id)
    ).one_or_none()
    if run_row is None:
        raise KeyError(f"Run not found: {run_id}")
    run = run_result_from_snapshot(run_row.result_snapshot)
    if run.status in {"completed", "failed"}:
        raise ValueError(f"Run is already terminal: {run_id} ({run.status})")

    cancelled_tasks, completed_task_ids = cancel_workflow_tasks(
        connection,
        tasks,
        run_id=run_id,
        reason=reason,
        now=now,
    )
    cancelled_transcript_ids = cancel_partial_transcripts(
        connection,
        run_id=run_id,
        now=now,
    )
    cancelled_run = run.model_copy(
        update={
            "status": "cancelled",
            "findings": [
                *run.findings,
                ValidationFinding(
                    severity="warning",
                    check="run.cancelled",
                    message=reason,
                ),
            ],
        }
    )
    connection.execute(
        update(report_runs_table)
        .where(report_runs_table.c.id == run_id)
        .values(
            status="cancelled",
            completed_at=now,
            updated_at=now,
            error_message=reason,
            result_snapshot=cancelled_run.model_dump(mode="json"),
        )
    )
    connection.execute(
        insert(run_events_table).values(
            id=f"event-{uuid4().hex[:12]}",
            run_id=run_id,
            status="cancelled",
            stage="cancelled",
            message=reason,
            created_at=now,
        )
    )
    return RunCancellationResult(
        run=cancelled_run,
        cancelled_task_ids=[task.id for task in cancelled_tasks],
        preserved_completed_task_ids=completed_task_ids,
        cancelled_transcript_ids=cancelled_transcript_ids,
    )


def cancel_workflow_tasks(
    connection: Connection,
    tasks: list[ProjectWorkflowTask],
    *,
    run_id: str,
    reason: str,
    now: datetime,
) -> tuple[list[ProjectWorkflowTask], list[str]]:
    terminal_statuses = {
        ProjectWorkflowTaskStatus.COMPLETED,
        ProjectWorkflowTaskStatus.FAILED,
        ProjectWorkflowTaskStatus.CANCELLED,
    }
    run_tasks = [task for task in tasks if getattr(task.input, "run_id", None) == run_id]
    completed_task_ids = [
        task.id for task in run_tasks if task.status is ProjectWorkflowTaskStatus.COMPLETED
    ]
    cancelled: list[ProjectWorkflowTask] = []
    for task in run_tasks:
        if task.status in terminal_statuses:
            continue
        updated = cancelled_workflow_task(task, reason=reason, now=now)
        connection.execute(
            update(project_workflow_tasks_table)
            .where(project_workflow_tasks_table.c.id == task.id)
            .values(**workflow_values(updated))
        )
        cancelled.append(updated)
    return cancelled, completed_task_ids


def cancelled_workflow_task(
    task: ProjectWorkflowTask,
    *,
    reason: str,
    now: datetime,
) -> ProjectWorkflowTask:
    return task.model_copy(
        update={
            "status": ProjectWorkflowTaskStatus.CANCELLED,
            "error_message": reason,
            "warnings": [*task.warnings, reason],
            "lease_token": None,
            "lease_expires_at": None,
            "completed_at": now,
            "progress": ProjectWorkflowProgress(
                stage=ProjectWorkflowStage.CANCELLED,
                message=reason,
                completed_items=task.progress.completed_items,
                total_items=task.progress.total_items,
                updated_at=now,
            ),
        }
    )


def cancel_partial_transcripts(
    connection: Connection,
    *,
    run_id: str,
    now: datetime,
) -> list[str]:
    rows = connection.execute(
        select(
            llm_conversations_table.c.id,
            llm_conversations_table.c.diagnostics,
        ).where(
            llm_conversations_table.c.run_id == run_id,
            llm_conversations_table.c.status == LLMConversationStatus.PARTIAL.value,
        )
    ).all()
    for row in rows:
        diagnostics = dict(row.diagnostics or {})
        diagnostics["termination"] = "cancelled_by_user"
        connection.execute(
            update(llm_conversations_table)
            .where(llm_conversations_table.c.id == row.id)
            .values(
                status=LLMConversationStatus.CANCELLED.value,
                completed_at=now,
                updated_at=now,
                diagnostics=diagnostics,
            )
        )
    return [row.id for row in rows]
