from __future__ import annotations

import pytest

from guidesync_agent.agent_runtime.pydantic_ai import PydanticAgentRunCancelledError
from guidesync_agent.schemas import ProjectConfig, ProjectProfileStatus
from guidesync_agent.services.project_profile import service as project_profile_service
from guidesync_agent.services.project_profile.service import build_project_profile_for_project


def test_failed_project_profile_summary_replaces_running_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_profile_agent(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("profile timeout")

    monkeypatch.setattr(project_profile_service, "run_project_profile_agent", fail_profile_agent)

    profile = build_project_profile_for_project(
        ProjectConfig(id="project-profile-failed", name="Profile failure"),
        reason="manual_profile_rebuild",
    )

    assert profile.status == ProjectProfileStatus.FAILED
    assert profile.summary == "Project profile build failed: profile timeout"
    assert profile.error_message == "profile timeout"
    assert "running" not in profile.summary


def test_cancelled_project_profile_is_not_persisted_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cancel_profile_agent(*_args: object, **_kwargs: object) -> object:
        raise PydanticAgentRunCancelledError("Cancelled in test.")

    monkeypatch.setattr(project_profile_service, "run_project_profile_agent", cancel_profile_agent)

    profile = build_project_profile_for_project(
        ProjectConfig(id="project-profile-cancelled", name="Profile cancellation"),
        reason="manual_profile_rebuild",
    )

    assert profile.status is ProjectProfileStatus.CANCELLED
    assert profile.summary == "Project profile build cancelled."
    assert profile.error_message == "Cancelled in test."
