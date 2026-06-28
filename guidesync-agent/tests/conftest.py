from __future__ import annotations

import pytest
from project_profile_fake_agent import FakeProjectProfileAgentProvider

from guidesync_agent.schemas import ProjectConfig, ProjectProfileSnapshot
from guidesync_agent.services import project_profile as project_profile_service
from guidesync_agent.services import project_profile_agent as project_profile_agent_service
from guidesync_agent.services.project_profile_agent import ProjectProfileRepositoryData


@pytest.fixture(autouse=True)
def use_isolated_unit_runtime(monkeypatch):
    monkeypatch.delenv("GUIDESYNC_DATABASE_URL", raising=False)
    monkeypatch.delenv("GUIDESYNC_PROJECT_PROFILE_AGENT_PROVIDER", raising=False)
    monkeypatch.setenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_PROVIDER", "deterministic")
    monkeypatch.setenv("GUIDESYNC_SCREENSHOT_VISION_PROVIDER", "deterministic_test")
    monkeypatch.setenv("GUIDESYNC_ARTIFACT_STORAGE", "file")
    # File stores are explicit unit-test compatibility only; Compose runtime uses Postgres.
    monkeypatch.setenv("GUIDESYNC_STORAGE_MODE", "file")
    monkeypatch.setenv("GUIDESYNC_SEMANTIC_RANKER_MODE", "deterministic_test")
    monkeypatch.setenv("GUIDESYNC_STORAGE_AUTO_CREATE_SCHEMA", "1")
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
        return project_profile_agent_service.run_project_profile_agent(
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
