from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def use_isolated_unit_runtime(monkeypatch):
    monkeypatch.delenv("GUIDESYNC_DATABASE_URL", raising=False)
    monkeypatch.setenv("GUIDESYNC_PROJECT_PROFILE_AGENT_PROVIDER", "fake")
    monkeypatch.delenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_PROVIDER", raising=False)
    monkeypatch.setenv("GUIDESYNC_SCREENSHOT_VISION_PROVIDER", "deterministic_test")
    monkeypatch.setenv("GUIDESYNC_ARTIFACT_STORAGE", "file")
    # File stores are explicit unit-test compatibility only; Compose runtime uses Postgres.
    monkeypatch.setenv("GUIDESYNC_STORAGE_MODE", "file")
    monkeypatch.setenv("GUIDESYNC_SEMANTIC_RANKER_MODE", "deterministic_test")
    monkeypatch.setenv("GUIDESYNC_STORAGE_AUTO_CREATE_SCHEMA", "1")
    monkeypatch.delenv("GUIDESYNC_REPOSITORY_SYNC_QUEUE_NAME", raising=False)
    monkeypatch.delenv("GUIDESYNC_REPOSITORY_SYNC_QUEUE_URL", raising=False)
    monkeypatch.delenv("GUIDESYNC_SQS_ENDPOINT_URL", raising=False)
