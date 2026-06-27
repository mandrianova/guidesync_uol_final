from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def use_fixture_project_profile_agent(monkeypatch):
    monkeypatch.setenv("GUIDESYNC_PROJECT_PROFILE_AGENT_PROVIDER", "fake")
