from __future__ import annotations

import os
from dataclasses import dataclass

from guidesync_agent.schemas import ProviderConfig, ProviderKind


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


def artifact_storage_config() -> ArtifactStorageConfig:
    return ArtifactStorageConfig(
        backend=os.environ.get("GUIDESYNC_ARTIFACT_STORAGE", "file").strip().lower(),
        bucket=os.environ.get("GUIDESYNC_S3_BUCKET") or None,
        endpoint_url=os.environ.get("GUIDESYNC_S3_ENDPOINT_URL") or None,
        region=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        prefix=os.environ.get("GUIDESYNC_S3_PREFIX", "reports").strip("/") or "reports",
        public_base_url=(os.environ.get("GUIDESYNC_S3_PUBLIC_BASE_URL") or "").rstrip("/") or None,
    )


def auth_config() -> AuthConfig:
    return AuthConfig(
        mode=os.environ.get("GUIDESYNC_AUTH_MODE", "none").strip().lower(),
        username=os.environ.get("GUIDESYNC_AUTH_USERNAME") or None,
        password=os.environ.get("GUIDESYNC_AUTH_PASSWORD") or None,
    )


def provider_config_from_env(fallback: ProviderConfig | None = None) -> ProviderConfig:
    base = fallback or ProviderConfig()
    provider = os.environ.get("GUIDESYNC_AGENT_PROVIDER")
    model = os.environ.get("GUIDESYNC_AGENT_MODEL")
    base_url = os.environ.get("GUIDESYNC_AGENT_BASE_URL")
    api_key_env = os.environ.get("GUIDESYNC_AGENT_API_KEY_ENV")
    timeout_seconds = os.environ.get("GUIDESYNC_AGENT_TIMEOUT_SECONDS")

    if not any([provider, model, base_url, api_key_env, timeout_seconds]):
        return base

    return ProviderConfig(
        provider=ProviderKind(provider) if provider else base.provider,
        model=model or base.model,
        name=base.name,
        base_url=base_url or base.base_url,
        api_key_env=api_key_env or base.api_key_env,
        timeout_seconds=int(timeout_seconds) if timeout_seconds else base.timeout_seconds,
        metadata=base.metadata,
    )


def public_runtime_config() -> dict[str, str | None]:
    provider = provider_config_from_env()
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
