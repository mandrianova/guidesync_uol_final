from __future__ import annotations

from guidesync_agent.schemas import (
    ModelProviderBundle,
    ModelProviderFamily,
    ModelRole,
    ProviderConfig,
    ProviderKind,
)
from guidesync_agent.services.model_roles import (
    attach_role_metadata,
    provider_config_for_role,
)


def test_code_change_role_config_reads_role_specific_env(monkeypatch) -> None:
    monkeypatch.setenv("GUIDESYNC_MODEL_BUNDLE", "google_all_in_one")
    monkeypatch.setenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_PROVIDER", "local_http")
    monkeypatch.setenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_PROVIDER_FAMILY", "google")
    monkeypatch.setenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_TIMEOUT_SECONDS", "300")

    config = provider_config_for_role(ModelRole.CODE_CHANGE_ANALYSIS)

    assert config.provider == ProviderKind.LOCAL_HTTP
    assert config.model == "gemini-3.5-flash"
    assert config.base_url == "https://example.test/v1"
    assert config.timeout_seconds == 300
    assert config.metadata["model_role"] == ModelRole.CODE_CHANGE_ANALYSIS.value
    assert config.metadata["model_bundle"] == ModelProviderBundle.GOOGLE_ALL_IN_ONE.value
    assert config.metadata["model_provider_family"] == ModelProviderFamily.GOOGLE.value


def test_orchestrator_role_metadata_preserves_requested_provider_config(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GUIDESYNC_AGENT_MODEL", "openai:google/gemma-4-31b-qat")
    requested = ProviderConfig(
        provider=ProviderKind.LOCAL_HTTP,
        model="openai:gpt-5.4-mini",
        base_url="https://models.example.test/v1",
        timeout_seconds=120,
    )

    config = attach_role_metadata(requested, ModelRole.ORCHESTRATOR)

    assert config.provider == ProviderKind.LOCAL_HTTP
    assert config.model == "openai:gpt-5.4-mini"
    assert config.metadata["model_role"] == ModelRole.ORCHESTRATOR.value
    assert config.metadata["model"] == "openai:gpt-5.4-mini"
    assert config.metadata["base_url"] == "https://models.example.test/v1"
