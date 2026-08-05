from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from guidesync_agent.schemas import ProviderConfig, ProviderKind, ThinkingSetting
from guidesync_agent.settings import get_settings


@dataclass(frozen=True)
class ArtifactStorageConfig:
    backend: str = "file"
    bucket: str | None = None
    endpoint_url: str | None = None
    region: str = "us-east-1"
    prefix: str = "reports"
    public_base_url: str | None = None


@dataclass(frozen=True)
class AuthConfig:
    mode: str = "none"
    username: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class CorsConfig:
    origins: list[str]
    allow_credentials: bool = True


def artifact_storage_config() -> ArtifactStorageConfig:
    settings = get_settings().artifact
    return ArtifactStorageConfig(
        backend=settings.backend.strip().lower(),
        bucket=settings.bucket or None,
        endpoint_url=settings.endpoint_url or None,
        region=settings.region,
        prefix=settings.prefix.strip("/") or "reports",
        public_base_url=(settings.public_base_url or "").rstrip("/") or None,
    )


def auth_config() -> AuthConfig:
    settings = get_settings().auth
    return AuthConfig(
        mode=settings.mode.strip().lower(),
        username=settings.username or None,
        password=settings.password.get_secret_value() if settings.password else None,
    )


def cors_config() -> CorsConfig:
    settings = get_settings().cors
    return CorsConfig(
        origins=settings.origins,
        allow_credentials=settings.allow_credentials,
    )


def provider_config_from_settings(fallback: ProviderConfig | None = None) -> ProviderConfig:
    base = fallback or ProviderConfig()
    runtime_settings = get_settings()
    settings = runtime_settings.models.orchestrator
    provider = settings.provider
    model = settings.model
    base_url = settings.base_url
    api_key_env = settings.api_key_env
    timeout_seconds = settings.timeout_seconds
    max_concurrent_agents = settings.max_concurrent_agents
    thinking = settings.thinking

    if not any(
        [
            provider,
            model,
            base_url,
            api_key_env,
            timeout_seconds,
            max_concurrent_agents,
            thinking,
        ]
    ):
        return base

    return ProviderConfig(
        provider=ProviderKind(provider) if provider else base.provider,
        model=model or base.model,
        name=base.name,
        base_url=base_url or base.base_url,
        api_key_env=api_key_env or base.api_key_env,
        api_key=base.api_key,
        timeout_seconds=int(timeout_seconds) if timeout_seconds else base.timeout_seconds,
        max_concurrent_agents=(
            int(max_concurrent_agents)
            if max_concurrent_agents
            else base.max_concurrent_agents
        ),
        thinking=parse_thinking_setting(thinking) if thinking else base.thinking,
        browser=base.browser or runtime_settings.browser.tool_settings(),
        metadata=base.metadata,
    )


def public_runtime_config() -> dict[str, str | None]:
    provider = provider_config_from_settings()
    storage = artifact_storage_config()
    auth = auth_config()
    return {
        "agent_provider": provider.provider.value,
        "agent_model": provider.model,
        "agent_base_url": provider.base_url,
        "artifact_storage": storage.backend,
        "artifact_bucket": storage.bucket,
        "auth_mode": auth.mode,
    }


def parse_thinking_setting(value: str) -> ThinkingSetting:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    allowed = {"minimal", "low", "medium", "high", "xhigh"}
    if normalized in allowed:
        return cast(ThinkingSetting, normalized)
    raise ValueError(
        "GUIDESYNC_AGENT_THINKING must be one of: true, false, minimal, low, medium, high, xhigh."
    )
