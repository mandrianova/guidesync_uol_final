from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

import pytest
from storage_test_utils import sqlite_database_url

from guidesync_agent.pipeline import save_run_state
from guidesync_agent.schemas import (
    GuideSyncRunRequest,
    ProjectCreate,
    ProjectRepository,
    ProviderConfig,
    ProviderKind,
    RepositoryInput,
    RepositorySyncTask,
)
from guidesync_agent.services.repositories.tasks import RepositoryTaskMessage
from guidesync_agent.storage import DatabaseProjectStore, DatabaseRunStore
from guidesync_agent.worker import (
    process_repository_queue_once,
    run_worker_loop,
    run_worker_once,
)


def run_git(repo: Path | None, args: list[str]) -> None:
    command = ["git", *args] if repo is None else ["git", "-C", str(repo), *args]
    subprocess.run(command, check=True, capture_output=True, text=True)


def test_worker_loop_retries_after_transient_iteration_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def run_once(coroutine) -> None:
        nonlocal attempts
        coroutine.close()
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary database failure")
        raise KeyboardInterrupt

    monkeypatch.setattr("guidesync_agent.worker.initialize_storage", lambda: None)
    monkeypatch.setattr("guidesync_agent.worker.asyncio.run", run_once)
    monkeypatch.setattr("guidesync_agent.worker.time.sleep", sleeps.append)

    with caplog.at_level(logging.ERROR), pytest.raises(KeyboardInterrupt):
        run_worker_loop(0.25)

    assert attempts == 2
    assert sleeps == [0.25]
    assert "Worker iteration failed" in caplog.text


def create_source_repository(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "docs").mkdir(parents=True)
    (source / "docs" / "guide.md").write_text("# Guide\n\nQueued sync.\n", encoding="utf-8")
    run_git(None, ["init", str(source)])
    run_git(source, ["config", "user.email", "test@example.com"])
    run_git(source, ["config", "user.name", "GuideSync Test"])
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Add docs"])
    run_git(source, ["branch", "-M", "main"])
    return source


def test_worker_claims_queued_run(monkeypatch, tmp_path) -> None:
    database_url = sqlite_database_url(tmp_path / "worker.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    request = GuideSyncRunRequest(
        run_id="worker-queued-run",
        goal="Process queued task.",
        provider=ProviderConfig(provider=ProviderKind.MOCK, model="mock:deterministic"),
        repositories=[RepositoryInput(name="repo", path=Path("."))],
    )
    save_run_state(request, "queued")

    result = asyncio.run(run_worker_once())
    stored = DatabaseRunStore(database_url).get("worker-queued-run")

    assert result is not None
    assert stored is not None
    assert stored.status == "completed"


def test_worker_processes_repository_sync_queue_message(monkeypatch, tmp_path: Path) -> None:
    class OneMessageQueue:
        def __init__(self, task: RepositorySyncTask) -> None:
            self.deleted_receipts: list[str] = []
            self.message = RepositoryTaskMessage(task=task, receipt_handle="receipt-1")

        def receive_repository_sync_tasks(
            self,
            *,
            max_messages: int = 1,
        ) -> list[RepositoryTaskMessage]:
            return [self.message]

        def delete_message(self, receipt_handle: str) -> None:
            self.deleted_receipts.append(receipt_handle)

    database_url = sqlite_database_url(tmp_path / "repository-worker.db")
    source = create_source_repository(tmp_path)
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "repository-cache"))
    store = DatabaseProjectStore(database_url)
    project = store.save(
        ProjectCreate(
            name="Repository worker project",
            repositories=[
                ProjectRepository(
                    id="repo-worker",
                    name="fixture",
                    url=str(source),
                    default_branch="main",
                    analysis_paths=["docs"],
                )
            ],
        ),
    )
    task = RepositorySyncTask(project_id=project.id, repository_id="repo-worker")
    queue = OneMessageQueue(task)
    monkeypatch.setattr("guidesync_agent.worker.RepositoryTaskQueue", lambda: queue)

    processed = process_repository_queue_once()
    loaded = store.get(project.id)

    assert processed is True
    assert queue.deleted_receipts == ["receipt-1"]
    assert loaded is not None
    assert loaded.repositories[0].cache_status == "ready"
    assert loaded.repositories[0].local_path
    assert loaded.repositories[0].current_commit
