from __future__ import annotations

from fastapi.testclient import TestClient

from guidesync_agent.api import app
from guidesync_agent.config import provider_config_from_env
from guidesync_agent.schemas import ProviderConfig, ProviderKind


def test_provider_config_from_env_overrides_fallback(monkeypatch) -> None:
    monkeypatch.setenv("GUIDESYNC_AGENT_PROVIDER", "local_http")
    monkeypatch.setenv("GUIDESYNC_AGENT_MODEL", "google/gemma-4-31b-qat")
    monkeypatch.setenv("GUIDESYNC_AGENT_BASE_URL", "http://localhost:1234/api/v1/chat")
    monkeypatch.setenv("GUIDESYNC_AGENT_TIMEOUT_SECONDS", "180")

    config = provider_config_from_env(ProviderConfig())

    assert config.provider == ProviderKind.LOCAL_HTTP
    assert config.model == "google/gemma-4-31b-qat"
    assert config.base_url == "http://localhost:1234/api/v1/chat"
    assert config.timeout_seconds == 180


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
