from __future__ import annotations

import os
from dataclasses import dataclass
from typing import cast

from guidesync_agent.llm.settings import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TIMEOUT_SECONDS,
)
from guidesync_agent.schemas import (
    ModelProviderBundle,
    ModelProviderFamily,
    ModelRole,
    ModelRoleSettings,
    ProviderConfig,
    ProviderKind,
    ThinkingSetting,
)


@dataclass(frozen=True)
class RoleEnvironment:
    prefix: str
    default_provider: ProviderKind
    default_supports_tool_use: bool = False
    default_supports_vision: bool = False


ROLE_ENVIRONMENTS = {
    ModelRole.ORCHESTRATOR: RoleEnvironment(
        prefix="GUIDESYNC_AGENT",
        default_provider=ProviderKind.PYDANTIC_AI,
        default_supports_tool_use=True,
    ),
    ModelRole.PROJECT_PROFILE_FILE_READER: RoleEnvironment(
        prefix="GUIDESYNC_PROJECT_PROFILE_AGENT",
        default_provider=ProviderKind.LOCAL_HTTP,
    ),
    ModelRole.CODE_CHANGE_ANALYSIS: RoleEnvironment(
        prefix="GUIDESYNC_CODE_CHANGE_ANALYSIS",
        default_provider=ProviderKind.LOCAL_HTTP,
    ),
    ModelRole.SCREENSHOT_VISION: RoleEnvironment(
        prefix="GUIDESYNC_SCREENSHOT_VISION",
        default_provider=ProviderKind.LOCAL_HTTP,
        default_supports_vision=True,
    ),
    ModelRole.EMBEDDING_RANKER: RoleEnvironment(
        prefix="GUIDESYNC_EMBEDDING",
        default_provider=ProviderKind.LOCAL_HTTP,
    ),
}


def model_role_settings_from_env(
    role: ModelRole,
    *,
    fallback: ProviderConfig | None = None,
    prefer_fallback_values: bool = False,
) -> ModelRoleSettings:
    env = ROLE_ENVIRONMENTS[role]
    prefix = env.prefix
    fallback_provider = fallback.provider if fallback else env.default_provider
    fallback_model = fallback.model if fallback else DEFAULT_LLM_MODEL
    fallback_base_url = fallback.base_url if fallback else DEFAULT_LLM_BASE_URL
    fallback_timeout = fallback.timeout_seconds if fallback else DEFAULT_LLM_TIMEOUT_SECONDS
    fallback_thinking = fallback.thinking if fallback else None
    raw_provider = os.environ.get(f"{prefix}_PROVIDER")
    if prefer_fallback_values:
        raw_provider = None
    model = (
        fallback_model
        if prefer_fallback_values
        else os.environ.get(f"{prefix}_MODEL") or fallback_model
    )
    base_url = None if prefer_fallback_values else os.environ.get(f"{prefix}_BASE_URL")
    if (
        base_url is None
        and not prefer_fallback_values
        and role is not ModelRole.ORCHESTRATOR
    ):
        base_url = os.environ.get("GUIDESYNC_LLM_BASE_URL")
    if base_url is None:
        base_url = fallback_base_url
    timeout_seconds = (
        fallback_timeout
        if prefer_fallback_values
        else int(os.environ.get(f"{prefix}_TIMEOUT_SECONDS") or fallback_timeout)
    )
    thinking = parse_optional_thinking(
        None if prefer_fallback_values else os.environ.get(f"{prefix}_THINKING"),
        fallback_thinking,
    )

    return ModelRoleSettings(
        role=role,
        bundle=parse_bundle(os.environ.get("GUIDESYNC_MODEL_BUNDLE")),
        provider_family=parse_provider_family(
            None
            if prefer_fallback_values
            else os.environ.get(f"{prefix}_PROVIDER_FAMILY")
            or os.environ.get("GUIDESYNC_MODEL_PROVIDER_FAMILY"),
            model,
        ),
        provider=parse_provider_kind(raw_provider, fallback_provider),
        model=model,
        name=None if prefer_fallback_values else os.environ.get(f"{prefix}_NAME"),
        base_url=base_url,
        api_key_env=(
            fallback.api_key_env
            if prefer_fallback_values and fallback
            else os.environ.get(f"{prefix}_API_KEY_ENV")
            or (fallback.api_key_env if fallback else None)
        ),
        timeout_seconds=timeout_seconds,
        thinking=thinking,
        max_output_tokens=optional_int(os.environ.get(f"{prefix}_MAX_OUTPUT_TOKENS")),
        context_budget_tokens=optional_int(os.environ.get(f"{prefix}_CONTEXT_BUDGET_TOKENS")),
        supports_structured_output=env_bool(f"{prefix}_SUPPORTS_STRUCTURED_OUTPUT", True),
        supports_tool_use=env_bool(f"{prefix}_SUPPORTS_TOOL_USE", env.default_supports_tool_use),
        supports_vision=env_bool(f"{prefix}_SUPPORTS_VISION", env.default_supports_vision),
        endpoint_type=os.environ.get(f"{prefix}_ENDPOINT_TYPE") or "openai_compatible",
        configured_provider=raw_provider,
    )


def provider_config_for_role(
    role: ModelRole,
    *,
    fallback: ProviderConfig | None = None,
) -> ProviderConfig:
    role_fallback = assigned_profile_provider_config(role) or fallback
    prefer_fallback_values = role_fallback is not None and role_fallback is not fallback
    role_settings = model_role_settings_from_env(
        role,
        fallback=role_fallback,
        prefer_fallback_values=prefer_fallback_values,
    )
    metadata = {
        **(role_fallback.metadata if role_fallback else {}),
        **role_settings.evidence_metadata(),
    }
    if prefer_fallback_values:
        metadata["role_profile_override"] = True
    if role_settings.max_output_tokens is not None:
        metadata["max_output_tokens"] = role_settings.max_output_tokens
    return ProviderConfig(
        provider=role_settings.provider,
        model=role_settings.model,
        name=role_settings.name or (role_fallback.name if role_fallback else None),
        base_url=role_settings.base_url,
        api_key_env=role_settings.api_key_env,
        api_key=api_key_from_env(role_settings.api_key_env, role_fallback),
        timeout_seconds=role_settings.timeout_seconds,
        thinking=role_settings.thinking,
        metadata=metadata,
    )


def attach_role_metadata(config: ProviderConfig, role: ModelRole) -> ProviderConfig:
    role_settings = model_role_settings_from_env(
        role,
        fallback=config,
        prefer_fallback_values=True,
    )
    role_metadata = {
        **role_settings.evidence_metadata(),
        "provider": config.provider.value,
        "model": config.model,
        "base_url": config.base_url,
        "api_key_env": config.api_key_env,
        "timeout_seconds": config.timeout_seconds,
        "thinking": config.thinking,
    }
    return config.model_copy(
        update={"metadata": {**config.metadata, **role_metadata}}
    )


def assigned_profile_provider_config(role: ModelRole) -> ProviderConfig | None:
    if not os.environ.get("GUIDESYNC_DATABASE_URL"):
        return None

    from guidesync_agent.storage import (
        GLOBAL_MODEL_PROFILE_ID,
        StorageConfigurationError,
        create_model_settings_store,
        model_settings_to_provider_config,
    )

    try:
        profiles = create_model_settings_store().list_profiles()
    except StorageConfigurationError:
        return None
    assigned_profile = next(
        (
            profile
            for profile in profiles
            if profile.id != GLOBAL_MODEL_PROFILE_ID and role in profile.roles
        ),
        None,
    )
    if assigned_profile is None:
        return None
    return model_settings_to_provider_config(assigned_profile)


def parse_provider_kind(value: str | None, fallback: ProviderKind) -> ProviderKind:
    if not value:
        return fallback
    try:
        return ProviderKind(value)
    except ValueError:
        return fallback


def parse_bundle(value: str | None) -> ModelProviderBundle:
    if not value:
        return ModelProviderBundle.LOCAL_OPEN_SOURCE
    try:
        return ModelProviderBundle(value.strip().lower())
    except ValueError:
        return ModelProviderBundle.CUSTOM


def parse_provider_family(value: str | None, model: str) -> ModelProviderFamily:
    if value:
        try:
            return ModelProviderFamily(value.strip().lower())
        except ValueError:
            return ModelProviderFamily.UNKNOWN
    normalized = model.lower()
    if "claude" in normalized or "anthropic" in normalized:
        return ModelProviderFamily.ANTHROPIC
    if "gemini" in normalized:
        return ModelProviderFamily.GOOGLE
    if "gpt-" in normalized and "gpt-oss" not in normalized:
        return ModelProviderFamily.OPENAI
    if "gemma" in normalized or "gpt-oss" in normalized:
        return ModelProviderFamily.OPEN_SOURCE
    return ModelProviderFamily.UNKNOWN


def parse_optional_thinking(
    value: str | None,
    fallback: ThinkingSetting | None,
) -> ThinkingSetting | None:
    if value is None:
        return fallback
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    allowed = {"minimal", "low", "medium", "high", "xhigh"}
    if normalized in allowed:
        return cast(ThinkingSetting, normalized)
    raise ValueError(
        "Thinking setting must be one of: true, false, minimal, low, medium, high, xhigh."
    )


def optional_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def env_bool(key: str, default: bool) -> bool:
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def api_key_from_env(
    api_key_env: str | None,
    fallback: ProviderConfig | None,
) -> str | None:
    if api_key_env:
        return os.environ.get(api_key_env)
    return fallback.api_key if fallback else None
