from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.engine import Connection

from guidesync_agent.models import (
    project_workflow_tasks_table,
    projects_table,
    report_runs_table,
    run_events_table,
)
from guidesync_agent.schemas import (
    ProjectWorkflowProgress,
    ProjectWorkflowStage,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProjectWorkflowTaskStatus,
    RunCancellationResult,
    VideoPresentationStatus,
)

from .run_cancellation import cancel_run_transaction
from .serialization import (
    find_active_dedupe_task,
    next_workflow_sequence,
    project_has_running_workflow,
    workflow_dependencies_completed,
    workflow_task_from_row,
    workflow_values,
)
from .serialization_runs import run_result_from_snapshot


class DatabaseProjectWorkflowStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        return None

    def enqueue(self, task: ProjectWorkflowTask) -> ProjectWorkflowTask:
        self.initialize()
        with self.engine.begin() as connection:
            connection.execute(
                select(projects_table.c.id)
                .where(projects_table.c.id == task.project_id)
                .with_for_update()
            ).one_or_none()
            tasks = self._list_tasks(connection, project_id=task.project_id)
            if task.dedupe_key:
                existing = find_active_dedupe_task(tasks, task.project_id, task.dedupe_key)
                if existing is not None:
                    return existing
            queued = task.model_copy(
                update={"sequence": next_workflow_sequence(tasks, task.project_id)}
            )
            connection.execute(
                insert(project_workflow_tasks_table).values(**workflow_values(queued))
            )
        return queued

    def save(self, task: ProjectWorkflowTask) -> ProjectWorkflowTask:
        self.initialize()
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(project_workflow_tasks_table.c.id).where(
                    project_workflow_tasks_table.c.id == task.id
                )
            ).one_or_none()
            values = workflow_values(task)
            if existing is None:
                connection.execute(insert(project_workflow_tasks_table).values(**values))
            else:
                connection.execute(
                    update(project_workflow_tasks_table)
                    .where(project_workflow_tasks_table.c.id == task.id)
                    .values(**values)
                )
        return task

    def get(self, task_id: str) -> ProjectWorkflowTask | None:
        self.initialize()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(project_workflow_tasks_table).where(
                    project_workflow_tasks_table.c.id == task_id
                )
            ).one_or_none()
        return workflow_task_from_row(row) if row else None

    def list_tasks(self, project_id: str | None = None) -> list[ProjectWorkflowTask]:
        self.initialize()
        with self.engine.begin() as connection:
            return self._list_tasks(connection, project_id=project_id)

    def claim_next(self) -> ProjectWorkflowTask | None:
        self.initialize()
        with self.engine.begin() as connection:
            tasks = self._list_tasks(connection, project_id=None)
            now = datetime.now(UTC)
            tasks = recover_expired_tasks(connection, tasks, now)
            task_by_id = {task.id: task for task in tasks}
            cancel_failed_dependents(connection, tasks, task_by_id, now)
            for listed_task in tasks:
                task = task_by_id[listed_task.id]
                if task.status not in {
                    ProjectWorkflowTaskStatus.QUEUED,
                    ProjectWorkflowTaskStatus.RETRYING,
                }:
                    continue
                if project_has_running_workflow(tasks, task.project_id):
                    continue
                if not workflow_dependencies_completed(task, task_by_id):
                    continue
                claimed = task.model_copy(
                    update={
                        "status": ProjectWorkflowTaskStatus.RUNNING,
                        "started_at": task.started_at or now,
                        "attempt_count": task.attempt_count + 1,
                        "lease_token": f"workflow-lease-{uuid4().hex}",
                        "lease_expires_at": now + timedelta(minutes=15),
                        "last_heartbeat_at": now,
                        "progress": ProjectWorkflowProgress(
                            stage=ProjectWorkflowStage.RUNNING,
                            message="Workflow task started",
                            updated_at=now,
                        ),
                    }
                )
                updated = connection.execute(
                    update(project_workflow_tasks_table)
                    .where(
                        project_workflow_tasks_table.c.id == claimed.id,
                        project_workflow_tasks_table.c.status.in_(
                            {
                                ProjectWorkflowTaskStatus.QUEUED.value,
                                ProjectWorkflowTaskStatus.RETRYING.value,
                            }
                        ),
                    )
                    .values(**workflow_values(claimed))
                )
                if updated.rowcount:
                    return claimed
        return None

    def heartbeat(
        self,
        task_id: str,
        lease_token: str,
        progress: ProjectWorkflowProgress | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        values: dict[str, object] = {
            "last_heartbeat_at": now,
            "lease_expires_at": now + timedelta(minutes=15),
        }
        if progress is not None:
            values["progress"] = progress.model_copy(update={"updated_at": now}).model_dump(
                mode="json"
            )
        with self.engine.begin() as connection:
            updated = connection.execute(
                update(project_workflow_tasks_table)
                .where(
                    project_workflow_tasks_table.c.id == task_id,
                    project_workflow_tasks_table.c.status
                    == ProjectWorkflowTaskStatus.RUNNING.value,
                    project_workflow_tasks_table.c.lease_token == lease_token,
                )
                .values(**values)
            )
        return bool(updated.rowcount)

    def cancel_run(
        self,
        run_id: str,
        *,
        reason: str,
    ) -> RunCancellationResult:
        with self.engine.begin() as connection:
            tasks = self._list_tasks(connection, project_id=None)
            return cancel_run_transaction(
                connection,
                tasks,
                run_id=run_id,
                reason=reason,
            )

    def _list_tasks(
        self,
        connection: Connection,
        *,
        project_id: str | None,
    ) -> list[ProjectWorkflowTask]:
        query = select(project_workflow_tasks_table).order_by(
            project_workflow_tasks_table.c.created_at,
            project_workflow_tasks_table.c.sequence,
        )
        if project_id is not None:
            query = query.where(project_workflow_tasks_table.c.project_id == project_id)
        rows = connection.execute(query).all()
        return [workflow_task_from_row(row) for row in rows]


def recover_expired_tasks(
    connection: Connection,
    tasks: list[ProjectWorkflowTask],
    now: datetime,
) -> list[ProjectWorkflowTask]:
    recovered = []
    for task in tasks:
        if task.status is not ProjectWorkflowTaskStatus.RUNNING or (
            task.lease_expires_at is not None and not lease_has_expired(task.lease_expires_at, now)
        ):
            recovered.append(task)
            continue
        exhausted = task.attempt_count >= task.max_attempts
        updated = task.model_copy(
            update={
                "status": (
                    ProjectWorkflowTaskStatus.FAILED
                    if exhausted
                    else ProjectWorkflowTaskStatus.RETRYING
                ),
                "error_message": "Workflow task lease expired." if exhausted else None,
                "completed_at": now if exhausted else None,
                "lease_token": None,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
            }
        )
        connection.execute(
            update(project_workflow_tasks_table)
            .where(project_workflow_tasks_table.c.id == task.id)
            .values(**workflow_values(updated))
        )
        if exhausted:
            account_for_expired_video_task(connection, updated, now)
        recovered.append(updated)
    return recovered


def account_for_expired_video_task(
    connection: Connection,
    task: ProjectWorkflowTask,
    now: datetime,
) -> None:
    if task.kind is not ProjectWorkflowTaskKind.VIDEO_PRESENTATION:
        return
    run_id = getattr(task.input, "run_id", None)
    if not isinstance(run_id, str):
        return
    row = connection.execute(
        select(report_runs_table.c.result_snapshot).where(report_runs_table.c.id == run_id)
    ).one_or_none()
    if row is None:
        return
    run = run_result_from_snapshot(row.result_snapshot)
    message = "Video presentation generation failed after its worker lease expired."
    failed_run = run.model_copy(
        update={
            "video_presentation": run.video_presentation.model_copy(
                update={
                    "status": VideoPresentationStatus.FAILED,
                    "workflow_task_id": task.id,
                    "error_message": message,
                }
            ),
        }
    )
    connection.execute(
        update(report_runs_table)
        .where(report_runs_table.c.id == run_id)
        .values(
            updated_at=now,
            result_snapshot=failed_run.model_dump(mode="json"),
        )
    )
    connection.execute(
        insert(run_events_table).values(
            id=f"event-{uuid4().hex[:12]}",
            run_id=run_id,
            status=run.status,
            stage="video_presentation",
            message=message,
            created_at=now,
        )
    )


def lease_has_expired(expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None:
        return expires_at <= now.replace(tzinfo=None)
    return expires_at <= now


def cancel_failed_dependents(
    connection: Connection,
    tasks: list[ProjectWorkflowTask],
    task_by_id: dict[str, ProjectWorkflowTask],
    now: datetime,
) -> None:
    failed_statuses = {
        ProjectWorkflowTaskStatus.FAILED,
        ProjectWorkflowTaskStatus.CANCELLED,
        ProjectWorkflowTaskStatus.BLOCKED,
    }
    for task in tasks:
        if task.status not in {
            ProjectWorkflowTaskStatus.QUEUED,
            ProjectWorkflowTaskStatus.RETRYING,
        }:
            continue
        failed_dependencies = [
            dependency_id
            for dependency_id in task.depends_on_task_ids
            if task_by_id.get(dependency_id) is not None
            and task_by_id[dependency_id].status in failed_statuses
        ]
        if not failed_dependencies:
            continue
        message = "Cancelled because prerequisite tasks failed: " + ", ".join(failed_dependencies)
        cancelled = task.model_copy(
            update={
                "status": ProjectWorkflowTaskStatus.CANCELLED,
                "error_message": message,
                "warnings": [*task.warnings, message],
                "completed_at": now,
                "progress": ProjectWorkflowProgress(
                    stage=ProjectWorkflowStage.CANCELLED,
                    message=message,
                    updated_at=now,
                ),
            }
        )
        connection.execute(
            update(project_workflow_tasks_table)
            .where(project_workflow_tasks_table.c.id == task.id)
            .values(**workflow_values(cancelled))
        )
        task_by_id[task.id] = cancelled
