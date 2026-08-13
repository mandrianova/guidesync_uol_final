from __future__ import annotations

from collections.abc import Callable

from guidesync_agent.schemas import ProjectWorkflowTaskStatus
from guidesync_agent.storage import create_project_workflow_store


class WorkflowTaskCancelledError(RuntimeError):
    """Raised when a running workflow observes a user cancellation."""


def raise_if_workflow_task_cancelled(workflow_task_id: str | None) -> None:
    workflow_task_cancellation_check(workflow_task_id)()


def workflow_task_cancellation_check(workflow_task_id: str | None) -> Callable[[], None]:
    if workflow_task_id is None:
        return lambda: None
    store = create_project_workflow_store()

    def check() -> None:
        task = store.get(workflow_task_id)
        if task is not None and task.status is ProjectWorkflowTaskStatus.CANCELLED:
            raise WorkflowTaskCancelledError(
                task.error_message or "Workflow task was cancelled."
            )

    return check
