from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import cast

from sqlalchemy.engine import Row

from guidesync_agent.schemas import (
    EffectiveModelConfiguration,
    ModelCallLedgerEntry,
    ModelCallStatus,
    ModelRole,
    ModelSettings,
    ModelSettingsUpdate,
    ProviderConfig,
    ProviderKind,
    ThinkingSetting,
    TokenUsageBreakdown,
    TokenUsageSource,
    TokenUsageSummaryItem,
)

from .config import GLOBAL_MODEL_PROFILE_ID


def model_settings_to_provider_config(settings: ModelSettings) -> ProviderConfig:
    return ProviderConfig(
        provider=settings.provider,
        model=settings.model,
        name=settings.name,
        base_url=settings.base_url,
        api_key=settings.api_key,
        timeout_seconds=settings.timeout_seconds,
        max_concurrent_agents=settings.max_concurrent_agents,
        thinking=settings.thinking,
        metadata={
            "model_profile_id": settings.id,
            "model_profile_name": settings.name,
            "model_profile_roles": [role.value for role in settings.roles],
        },
    )

def effective_model_configuration_from_provider_config(
    config: ProviderConfig,
) -> EffectiveModelConfiguration:
    return EffectiveModelConfiguration(
        model_profile_id=config.metadata.get("model_profile_id"),
        name=config.name,
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        max_concurrent_agents=config.max_concurrent_agents,
        thinking=config.thinking,
        metadata=config.metadata,
    )

def model_settings_from_provider_config(config: ProviderConfig) -> ModelSettings:
    return ModelSettings(
        id=config.metadata.get("model_profile_id", GLOBAL_MODEL_PROFILE_ID),
        name=config.name or "Default model",
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        has_api_key=bool(config.api_key),
        is_default=True,
        timeout_seconds=config.timeout_seconds,
        max_concurrent_agents=config.max_concurrent_agents,
        thinking=config.thinking,
        roles=decode_model_roles(config.metadata.get("model_profile_roles")),
    )

def model_call_ledger_values(entry: ModelCallLedgerEntry) -> dict[str, object]:
    usage = entry.usage
    return {
        "id": entry.id,
        "project_id": entry.project_id,
        "run_id": entry.run_id,
        "workflow_task_id": entry.workflow_task_id,
        "parent_call_id": entry.parent_call_id,
        "role": entry.role.value,
        "provider": entry.provider.value,
        "model": entry.model,
        "model_profile_id": entry.model_profile_id,
        "endpoint_type": entry.endpoint_type,
        "base_url_host_hash": entry.base_url_host_hash,
        "deployment_id": entry.deployment_id,
        "prompt_version": entry.prompt_version,
        "structured_output_schema": entry.structured_output_schema,
        "status": entry.status.value,
        "started_at": entry.started_at,
        "completed_at": entry.completed_at,
        "latency_ms": entry.latency_ms,
        "usage_source": entry.usage_source.value,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "image_input_tokens": usage.image_input_tokens,
        "image_input_units": usage.image_input_units,
        "embedding_input_tokens": usage.embedding_input_tokens,
        "tool_call_count": usage.tool_call_count,
        "model_turn_count": usage.model_turn_count,
        "context_compaction_input_tokens": usage.context_compaction_input_tokens,
        "context_compaction_output_tokens": usage.context_compaction_output_tokens,
        "provider_reported_total_tokens": usage.provider_reported_total_tokens,
        "locally_estimated_total_tokens": usage.locally_estimated_total_tokens,
        "request_artifact_ref": entry.request_artifact_ref,
        "response_artifact_ref": entry.response_artifact_ref,
        "warnings": entry.warnings,
        "error": entry.error,
    }

def model_call_ledger_from_row(row: Row) -> ModelCallLedgerEntry:
    return ModelCallLedgerEntry(
        id=row.id,
        project_id=row.project_id,
        run_id=row.run_id,
        workflow_task_id=row.workflow_task_id,
        parent_call_id=row.parent_call_id,
        role=ModelRole(row.role),
        provider=ProviderKind(row.provider),
        model=row.model,
        model_profile_id=row.model_profile_id,
        endpoint_type=row.endpoint_type,
        base_url_host_hash=row.base_url_host_hash,
        deployment_id=row.deployment_id,
        prompt_version=row.prompt_version,
        structured_output_schema=row.structured_output_schema,
        status=ModelCallStatus(row.status),
        started_at=row.started_at,
        completed_at=row.completed_at,
        latency_ms=row.latency_ms,
        usage_source=TokenUsageSource(row.usage_source),
        usage=TokenUsageBreakdown(
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            reasoning_tokens=row.reasoning_tokens,
            cached_input_tokens=row.cached_input_tokens,
            cache_write_tokens=row.cache_write_tokens,
            image_input_tokens=row.image_input_tokens,
            image_input_units=row.image_input_units,
            embedding_input_tokens=row.embedding_input_tokens,
            tool_call_count=row.tool_call_count,
            model_turn_count=row.model_turn_count,
            context_compaction_input_tokens=row.context_compaction_input_tokens,
            context_compaction_output_tokens=row.context_compaction_output_tokens,
            provider_reported_total_tokens=row.provider_reported_total_tokens,
            locally_estimated_total_tokens=row.locally_estimated_total_tokens,
        ),
        request_artifact_ref=row.request_artifact_ref,
        response_artifact_ref=row.response_artifact_ref,
        warnings=list(row.warnings or []),
        error=row.error,
    )

def summarize_usage_items(
    entries: list[ModelCallLedgerEntry],
    key_for_entry: Callable[[ModelCallLedgerEntry], str],
) -> list[TokenUsageSummaryItem]:
    items: dict[str, TokenUsageSummaryItem] = {}
    for entry in entries:
        key = key_for_entry(entry)
        current = items.get(key) or TokenUsageSummaryItem(key=key)
        items[key] = current.model_copy(
            update={
                "input_tokens": current.input_tokens + (entry.usage.input_tokens or 0),
                "output_tokens": current.output_tokens + (entry.usage.output_tokens or 0),
                "total_tokens": current.total_tokens + ledger_total_usage_tokens(entry.usage),
                "estimated_tokens": current.estimated_tokens
                + (entry.usage.locally_estimated_total_tokens or 0),
                "calls": current.calls + 1,
                "warnings": [*current.warnings, *usage_entry_warnings(entry)],
            }
        )
    return sorted(items.values(), key=lambda item: item.key)

def usage_entry_warnings(entry: ModelCallLedgerEntry) -> list[str]:
    warnings = list(entry.warnings)
    if entry.usage_source is TokenUsageSource.LOCAL_ESTIMATE:
        warnings.append(f"{entry.id}: token usage is locally estimated")
    if entry.usage_source is TokenUsageSource.NOT_AVAILABLE:
        warnings.append(f"{entry.id}: token usage is unavailable")
    if entry.error:
        warnings.append(f"{entry.id}: {entry.error}")
    return warnings

def ledger_total_usage_tokens(breakdown: TokenUsageBreakdown) -> int:
    return (
        breakdown.provider_reported_total_tokens
        or breakdown.locally_estimated_total_tokens
        or sum(
            value or 0
            for value in [
                breakdown.input_tokens,
                breakdown.output_tokens,
                breakdown.reasoning_tokens,
                breakdown.image_input_tokens,
                breakdown.embedding_input_tokens,
            ]
        )
    )

def model_profile_roles_from_update(
    settings: ModelSettingsUpdate,
    existing: ModelSettings | None,
) -> list[ModelRole]:
    if settings.roles is None:
        return list(existing.roles) if existing else []
    return list(dict.fromkeys(settings.roles))

def remove_model_profile_roles(
    profile: ModelSettings,
    assigned_roles: Sequence[ModelRole],
) -> ModelSettings:
    if not assigned_roles:
        return profile
    next_roles = [role for role in profile.roles if role not in assigned_roles]
    if next_roles == profile.roles:
        return profile
    return profile.model_copy(update={"roles": next_roles})

def encode_model_roles(roles: Sequence[ModelRole]) -> list[str]:
    return [role.value for role in roles]

def decode_model_roles(value: object) -> list[ModelRole]:
    if not value:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(ModelRole(item) for item in value))

def encode_local_api_key(api_key: str | None) -> str | None:
    return f"local-inline:{api_key}" if api_key else None

def decode_local_api_key(secret_ref: str | None) -> str | None:
    if not secret_ref:
        return None
    if secret_ref.startswith("local-inline:"):
        return secret_ref.removeprefix("local-inline:")
    return None

def encode_thinking_setting(thinking: ThinkingSetting | None) -> str | None:
    if thinking is None:
        return None
    if isinstance(thinking, bool):
        return "true" if thinking else "false"
    return thinking

def decode_thinking_setting(value: str | None) -> ThinkingSetting | None:
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    return cast(ThinkingSetting, value)
