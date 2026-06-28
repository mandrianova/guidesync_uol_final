from __future__ import annotations

import pytest
from project_profile_fake_agent import FakeProjectProfileAgentProvider
from storage_test_utils import sqlite_database_url

from guidesync_agent.agent_runtime import project_profile as project_profile_agent_runtime
from guidesync_agent.agent_runtime.project_profile import ProjectProfileRepositoryData
from guidesync_agent.schemas import ProjectConfig, ProjectProfileSnapshot
from guidesync_agent.services import project_profile as project_profile_service


@pytest.fixture(autouse=True)
def use_isolated_unit_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "guidesync.db"))
    monkeypatch.delenv("GUIDESYNC_PROJECT_PROFILE_AGENT_PROVIDER", raising=False)
    monkeypatch.setenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_PROVIDER", "deterministic")
    monkeypatch.setenv("GUIDESYNC_SCREENSHOT_VISION_PROVIDER", "deterministic_test")
    monkeypatch.setenv("GUIDESYNC_ARTIFACT_STORAGE", "file")
    monkeypatch.setenv("GUIDESYNC_SEMANTIC_RANKER_MODE", "deterministic_test")
    monkeypatch.delenv("GUIDESYNC_REPOSITORY_SYNC_QUEUE_NAME", raising=False)
    monkeypatch.delenv("GUIDESYNC_REPOSITORY_SYNC_QUEUE_URL", raising=False)
    monkeypatch.delenv("GUIDESYNC_SQS_ENDPOINT_URL", raising=False)

    def run_project_profile_agent_with_fixture(
        project: ProjectConfig,
        base_profile: ProjectProfileSnapshot,
        repository_data: list[ProjectProfileRepositoryData],
        *,
        provider=None,
        reason: str = "manual",
        workflow_task_id: str | None = None,
    ):
        return project_profile_agent_runtime.run_project_profile_agent(
            project,
            base_profile,
            repository_data,
            provider=provider or FakeProjectProfileAgentProvider(),
            reason=reason,
            workflow_task_id=workflow_task_id,
        )

    monkeypatch.setattr(
        project_profile_service,
        "run_project_profile_agent",
        run_project_profile_agent_with_fixture,
    )
