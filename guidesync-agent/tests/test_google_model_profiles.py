from __future__ import annotations

from storage_test_utils import sqlite_database_url

from guidesync_agent.google_model_profiles import (
    GoogleModelProfileSeedOptions,
    seed_google_model_profiles,
)
from guidesync_agent.schemas import ModelRole, ProviderKind
from guidesync_agent.services.model_roles import provider_config_for_role
from guidesync_agent.storage import GLOBAL_MODEL_PROFILE_ID, DatabaseModelSettingsStore


def test_seed_google_model_profiles_is_idempotent(tmp_path) -> None:
    database_url = sqlite_database_url(tmp_path / "google-model-profiles.db")

    first = seed_google_model_profiles(configured_database_url=database_url)
    second = seed_google_model_profiles(configured_database_url=database_url)

    store = DatabaseModelSettingsStore(database_url)
    profiles = {profile.id: profile for profile in store.list_profiles()}

    assert [profile.id for profile in first] == [profile.id for profile in second]
    assert {
        GLOBAL_MODEL_PROFILE_ID,
        "google-gemini-orchestrator",
        "google-gemini-analysis",
        "google-gemini-screenshot-vision",
    }.issubset(profiles)
    assert profiles[GLOBAL_MODEL_PROFILE_ID].is_default is True
    assert profiles["google-gemini-orchestrator"].roles == [ModelRole.ORCHESTRATOR]
    assert profiles["google-gemini-analysis"].roles == [
        ModelRole.PROJECT_PROFILE_FILE_READER,
        ModelRole.CODE_CHANGE_ANALYSIS,
    ]
    assert profiles["google-gemini-screenshot-vision"].roles == [ModelRole.SCREENSHOT_VISION]
    assert all(profile.max_concurrent_agents == 1 for profile in profiles.values())


def test_seeded_google_role_profile_overrides_local_fallback(monkeypatch, tmp_path) -> None:
    database_url = sqlite_database_url(tmp_path / "google-role-resolution.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setenv("GUIDESYNC_AGENT_MODEL", "openai-chat:local-default")
    monkeypatch.setenv("GUIDESYNC_AGENT_BASE_URL", "http://host.docker.internal:1234/v1")

    seed_google_model_profiles(
        configured_database_url=database_url,
        options=GoogleModelProfileSeedOptions(
            orchestrator_model="google-cloud:gemini-test-pro",
            analysis_model="google-cloud:gemini-test-flash",
            screenshot_model="google-cloud:gemini-test-flash",
        ),
    )

    config = provider_config_for_role(ModelRole.ORCHESTRATOR)

    assert config.provider == ProviderKind.PYDANTIC_AI
    assert config.model == "google-cloud:gemini-test-pro"
    assert config.base_url is None
    assert config.metadata["role_profile_override"] is True
    assert config.metadata["endpoint_type"] == "google_cloud_vertex_ai"


def test_missing_role_profile_uses_env_fallback(monkeypatch, tmp_path) -> None:
    database_url = sqlite_database_url(tmp_path / "local-role-fallback.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_PROVIDER", "pydantic_ai")
    monkeypatch.setenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_MODEL", "openai-chat:local-default")
    monkeypatch.setenv(
        "GUIDESYNC_CODE_CHANGE_ANALYSIS_BASE_URL",
        "http://host.docker.internal:1234/v1",
    )

    config = provider_config_for_role(ModelRole.CODE_CHANGE_ANALYSIS)

    assert config.provider == ProviderKind.PYDANTIC_AI
    assert config.model == "openai-chat:local-default"
    assert config.base_url == "http://host.docker.internal:1234/v1"
    assert "role_profile_override" not in config.metadata
