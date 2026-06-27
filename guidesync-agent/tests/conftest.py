from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def use_fixture_project_profile_agent(monkeypatch):
    monkeypatch.delenv("GUIDESYNC_DATABASE_URL", raising=False)
    monkeypatch.setenv("GUIDESYNC_PROJECT_PROFILE_AGENT_PROVIDER", "fake")
    monkeypatch.setenv("GUIDESYNC_ARTIFACT_STORAGE", "file")
    monkeypatch.setenv("GUIDESYNC_STORAGE_MODE", "file")
    monkeypatch.setenv("GUIDESYNC_STORAGE_AUTO_CREATE_SCHEMA", "1")
    monkeypatch.delenv("GUIDESYNC_REPOSITORY_SYNC_QUEUE_NAME", raising=False)
    monkeypatch.delenv("GUIDESYNC_REPOSITORY_SYNC_QUEUE_URL", raising=False)
    monkeypatch.delenv("GUIDESYNC_SQS_ENDPOINT_URL", raising=False)
