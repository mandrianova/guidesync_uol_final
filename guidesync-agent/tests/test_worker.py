from __future__ import annotations

import asyncio
from pathlib import Path

from guidesync_agent.pipeline import save_run_state
from guidesync_agent.schemas import (
    GuideSyncRunRequest,
    ProviderConfig,
    ProviderKind,
    RepositoryInput,
)
from guidesync_agent.storage import DatabaseRunStore
from guidesync_agent.worker import run_worker_once


def test_worker_claims_queued_run(monkeypatch, tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'worker.db'}"
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
