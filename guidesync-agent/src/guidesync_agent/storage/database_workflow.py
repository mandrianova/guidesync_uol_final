from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.engine import Connection

from guidesync_agent.models import (
    project_workflow_tasks_table,
)
from guidesync_agent.schemas import (
    ProjectWorkflowTask,
    ProjectWorkflowTaskStatus,
)

from .serialization import (
    find_active_dedupe_task,
    next_workflow_sequence,
    project_has_running_workflow,
    workflow_dependencies_completed,
    workflow_task_from_row,
    workflow_values,
)


class DatabaseProjectWorkflowStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        return None

    def enqueue(self, task: ProjectWorkflowTask) -> ProjectWorkflowTask:
        self.initialize()
        with self.engine.begin() as connection:
            tasks = self._list_tasks(connection, project_id=task.project_id)
            if task.dedupe_key:
                existing = find_active_dedupe_task(tasks, task.project_id, task.dedupe_key)
                if existing is not None:
                    return existing
            queued = task.model_copy(
                update={"sequence": next_workflow_sequence(tasks, task.project_id)}
            )
            connection.execute(insert(project_workflow_tasks_table).values(**workflow_values(queued)))
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
            task_by_id = {task.id: task for task in tasks}
            for task in tasks:
                if task.status != ProjectWorkflowTaskStatus.QUEUED:
                    continue
                if project_has_running_workflow(tasks, task.project_id):
                    continue
                if not workflow_dependencies_completed(task, task_by_id):
                    continue
                claimed = task.model_copy(
                    update={
                        "status": ProjectWorkflowTaskStatus.RUNNING,
                        "started_at": datetime.now(UTC),
                    }
                )
                connection.execute(
                    update(project_workflow_tasks_table)
                    .where(project_workflow_tasks_table.c.id == claimed.id)
                    .values(**workflow_values(claimed))
                )
                return claimed
        return None

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
