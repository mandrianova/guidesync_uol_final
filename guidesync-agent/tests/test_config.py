from __future__ import annotations

from fastapi.testclient import TestClient

from guidesync_agent.api import app
from guidesync_agent.config import cors_config, provider_config_from_env
from guidesync_agent.schemas import ProviderConfig, ProviderKind


def test_provider_config_defaults_to_lm_studio_agent_mode(monkeypatch) -> None:
    monkeypatch.delenv("GUIDESYNC_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("GUIDESYNC_AGENT_MODEL", raising=False)
    monkeypatch.delenv("GUIDESYNC_AGENT_BASE_URL", raising=False)
    monkeypatch.delenv("GUIDESYNC_AGENT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("GUIDESYNC_AGENT_THINKING", raising=False)

    config = provider_config_from_env()

    assert config.provider == ProviderKind.PYDANTIC_AI
    assert config.model == "openai:google/gemma-4-31b-qat"
    assert config.base_url == "http://host.docker.internal:1234/v1"
    assert config.thinking is None


def test_provider_config_from_env_overrides_fallback(monkeypatch) -> None:
    monkeypatch.setenv("GUIDESYNC_AGENT_PROVIDER", "local_http")
    monkeypatch.setenv("GUIDESYNC_AGENT_MODEL", "google/gemma-4-31b-qat")
    monkeypatch.setenv("GUIDESYNC_AGENT_BASE_URL", "http://localhost:1234/api/v1/chat")
    monkeypatch.setenv("GUIDESYNC_AGENT_TIMEOUT_SECONDS", "180")
    monkeypatch.setenv("GUIDESYNC_AGENT_THINKING", "high")

    config = provider_config_from_env(ProviderConfig())

    assert config.provider == ProviderKind.LOCAL_HTTP
    assert config.model == "google/gemma-4-31b-qat"
    assert config.base_url == "http://localhost:1234/api/v1/chat"
    assert config.timeout_seconds == 180
    assert config.thinking == "high"


def test_provider_config_from_env_accepts_boolean_thinking(monkeypatch) -> None:
    monkeypatch.setenv("GUIDESYNC_AGENT_THINKING", "true")

    config = provider_config_from_env(ProviderConfig())

    assert config.thinking is True


def test_provider_config_does_not_serialize_inline_api_key() -> None:
    config = ProviderConfig(
        provider=ProviderKind.LOCAL_HTTP,
        model="google/gemma-4-31b-qat",
        api_key="secret-token",
    )

    dumped = config.model_dump(mode="json")

    assert "api_key" not in dumped


def test_basic_auth_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("GUIDESYNC_AUTH_MODE", raising=False)
    client = TestClient(app)

    response = client.get("/config")

    assert response.status_code == 200


def test_basic_auth_enabled_for_ui_and_api(monkeypatch) -> None:
    monkeypatch.setenv("GUIDESYNC_AUTH_MODE", "basic")
    monkeypatch.setenv("GUIDESYNC_AUTH_USERNAME", "demo")
    monkeypatch.setenv("GUIDESYNC_AUTH_PASSWORD", "secret")
    client = TestClient(app)

    rejected = client.get("/config")
    accepted = client.get("/config", auth=("demo", "secret"))
    health = client.get("/health")

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert health.status_code == 200


def test_cors_config_reads_allowed_origins(monkeypatch) -> None:
    monkeypatch.setenv(
        "GUIDESYNC_CORS_ORIGINS",
        "https://guidesync.devlogirl.com/, http://127.0.0.1:5173",
    )
    monkeypatch.setenv("GUIDESYNC_CORS_ALLOW_CREDENTIALS", "false")

    config = cors_config()

    assert config.origins == [
        "https://guidesync.devlogirl.com",
        "http://127.0.0.1:5173",
    ]
    assert config.allow_credentials is False


def test_basic_auth_does_not_reject_cors_preflight(monkeypatch) -> None:
    monkeypatch.setenv("GUIDESYNC_AUTH_MODE", "basic")
    monkeypatch.setenv("GUIDESYNC_AUTH_USERNAME", "demo")
    monkeypatch.setenv("GUIDESYNC_AUTH_PASSWORD", "secret")
    client = TestClient(app)

    response = client.options(
        "/config",
        headers={
            "Origin": "https://guidesync.devlogirl.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code != 401
