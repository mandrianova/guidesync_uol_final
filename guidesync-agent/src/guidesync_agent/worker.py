from __future__ import annotations

import argparse
import asyncio
import logging
import time

from guidesync_agent.app_logging import configure_logging
from guidesync_agent.controllers.repositories import process_repository_sync_task
from guidesync_agent.pipeline import run_guidesync, save_run_state
from guidesync_agent.schemas import (
    GuideSyncRunResult,
    ProjectProfileTask,
    RepositorySyncTask,
    ValidationFinding,
)
from guidesync_agent.services.repositories.tasks import RepositoryTaskQueue
from guidesync_agent.services.workflows.executor import ProjectWorkflowExecutor
from guidesync_agent.storage import create_run_store, initialize_storage
from guidesync_agent.workflows.project_profile import run_project_profile_workflow

logger = logging.getLogger(__name__)


async def run_worker_once() -> GuideSyncRunResult | None:
    workflow_task = ProjectWorkflowExecutor().claim_next_task()
    if workflow_task is not None:
        await ProjectWorkflowExecutor().execute(workflow_task)
        return None
    if process_repository_queue_once():
        return None
    store = create_run_store()
    claimed = store.claim_next_queued_run()
    if claimed is None:
        return None
    try:
        return await run_guidesync(claimed.request)
    except Exception as exc:  # noqa: BLE001 - worker must persist pipeline failure
        return save_run_state(
            claimed.request,
            "failed",
            [ValidationFinding(severity="error", check="worker", message=str(exc))],
        )


def process_repository_queue_once() -> bool:
    queue = RepositoryTaskQueue()
    if hasattr(queue, "receive_tasks"):
        messages = queue.receive_tasks(max_messages=1)
    else:
        messages = queue.receive_repository_sync_tasks(max_messages=1)
    if not messages:
        return False
    message = messages[0]
    try:
        if isinstance(message.task, RepositorySyncTask):
            process_repository_sync_task(message.task)
        elif isinstance(message.task, ProjectProfileTask):
            run_project_profile_workflow(message.task)
    except Exception:
        logger.exception("Background task failed: %s", message.task.model_dump(mode="json"))
        return True
    queue.delete_message(message.receipt_handle)
    return True


def run_worker_loop(interval_seconds: float) -> None:
    initialize_storage()
    while True:
        result = asyncio.run(run_worker_once())
        if result is None:
            time.sleep(interval_seconds)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Run the GuideSync background worker.")
    parser.add_argument("--interval", default=5.0, type=float, help="Polling interval in seconds.")
    parser.add_argument("--once", action="store_true", help="Process at most one queued run.")
    args = parser.parse_args()
    initialize_storage()
    if args.once:
        asyncio.run(run_worker_once())
        return
    run_worker_loop(args.interval)


if __name__ == "__main__":
    main()
