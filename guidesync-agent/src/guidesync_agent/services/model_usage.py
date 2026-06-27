from __future__ import annotations

import hashlib
from typing import Any, cast
from urllib.parse import urlparse

from guidesync_agent.schemas import (
    ModelCallLedgerEntry,
    ModelCallStatus,
    ModelRole,
    ProviderConfig,
    ProviderKind,
    ProviderRunMetadata,
    TokenUsageBreakdown,
    TokenUsageSource,
)
from guidesync_agent.services.context_budget import TOKEN_CHAR_RATIO


def normalize_token_usage(
    payload: object,
    *,
    fallback_input_text: str = "",
    fallback_output_text: str = "",
    tool_call_count: int = 0,
    model_turn_count: int = 1,
    image_input_units: int | None = None,
    embedding_input_tokens: int | None = None,
    context_compaction_input_tokens: int | None = None,
    context_compaction_output_tokens: int | None = None,
) -> tuple[TokenUsageBreakdown, TokenUsageSource]:
    usage = usage_payload(payload)
    provider_breakdown = provider_reported_breakdown(usage) if usage else None
    if provider_breakdown is not None:
        return (
            provider_breakdown.model_copy(
                update={
                    "tool_call_count": tool_call_count,
                    "model_turn_count": model_turn_count,
                    "image_input_units": image_input_units,
                    "embedding_input_tokens": embedding_input_tokens,
                    "context_compaction_input_tokens": context_compaction_input_tokens,
                    "context_compaction_output_tokens": context_compaction_output_tokens,
                }
            ),
            TokenUsageSource.PROVIDER_REPORTED,
        )

    metadata_estimate = estimated_breakdown_from_metadata(
        usage,
        tool_call_count=tool_call_count,
        model_turn_count=model_turn_count,
        image_input_units=image_input_units,
        embedding_input_tokens=embedding_input_tokens,
        context_compaction_input_tokens=context_compaction_input_tokens,
        context_compaction_output_tokens=context_compaction_output_tokens,
    )
    if metadata_estimate is not None:
        return metadata_estimate, TokenUsageSource.LOCAL_ESTIMATE

    estimated = estimate_total_tokens(fallback_input_text, fallback_output_text)
    source = (
        TokenUsageSource.LOCAL_ESTIMATE
        if estimated is not None
        else TokenUsageSource.NOT_AVAILABLE
    )
    return (
        TokenUsageBreakdown(
            input_tokens=estimate_tokens(fallback_input_text) if fallback_input_text else None,
            output_tokens=estimate_tokens(fallback_output_text) if fallback_output_text else None,
            image_input_units=image_input_units,
            embedding_input_tokens=embedding_input_tokens,
            tool_call_count=tool_call_count,
            model_turn_count=model_turn_count,
            context_compaction_input_tokens=context_compaction_input_tokens,
            context_compaction_output_tokens=context_compaction_output_tokens,
            locally_estimated_total_tokens=estimated,
        ),
        source,
    )


def usage_payload(payload: object) -> dict[str, Any] | None:
    if payload is None:
        return None
    raw = payload
    raw_dump = getattr(raw, "model_dump", None)
    if callable(raw_dump):
        raw = raw_dump()
    if not isinstance(raw, dict):
        return None
    usage = raw.get("usage") if "usage" in raw else raw
    usage_dump = getattr(usage, "model_dump", None)
    if callable(usage_dump):
        usage = usage_dump()
    return cast(dict[str, Any], usage) if isinstance(usage, dict) else None


def provider_reported_breakdown(usage: dict[str, Any]) -> TokenUsageBreakdown | None:
    input_tokens = int_value(usage, "input_tokens", "prompt_tokens", "promptTokenCount")
    output_tokens = int_value(usage, "output_tokens", "completion_tokens", "candidatesTokenCount")
    total_tokens = int_value(usage, "total_tokens", "totalTokenCount")
    cached_tokens = int_value(usage, "cached_input_tokens", "cache_read_input_tokens")
    cache_write_tokens = int_value(usage, "cache_write_tokens", "cache_creation_input_tokens")
    reasoning_tokens = int_value(usage, "reasoning_tokens", "thoughtsTokenCount")

    prompt_details = nested_dict(usage, "prompt_tokens_details")
    completion_details = nested_dict(usage, "completion_tokens_details")
    if prompt_details:
        cached_tokens = cached_tokens or int_value(prompt_details, "cached_tokens")
    if completion_details:
        reasoning_tokens = reasoning_tokens or int_value(completion_details, "reasoning_tokens")

    if all(
        value is None
        for value in [
            input_tokens,
            output_tokens,
            total_tokens,
            cached_tokens,
            cache_write_tokens,
            reasoning_tokens,
        ]
    ):
        return None

    return TokenUsageBreakdown(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        cached_input_tokens=cached_tokens,
        cache_write_tokens=cache_write_tokens,
        provider_reported_total_tokens=total_tokens,
    )


def estimated_breakdown_from_metadata(
    usage: dict[str, Any] | None,
    *,
    tool_call_count: int,
    model_turn_count: int,
    image_input_units: int | None,
    embedding_input_tokens: int | None,
    context_compaction_input_tokens: int | None,
    context_compaction_output_tokens: int | None,
) -> TokenUsageBreakdown | None:
    if not usage:
        return None
    prompt_chars = sum(
        int_value(usage, key) or 0
        for key in [
            "prompt_input_chars",
            "prompt_chunk_input_chars",
            "input_chars",
        ]
    )
    output_chars = int_value(usage, "prompt_output_chars", "output_chars") or 0
    input_tokens = estimate_tokens_from_chars(prompt_chars)
    output_tokens = estimate_tokens_from_chars(output_chars)
    total = sum(
        value or 0
        for value in [
            input_tokens,
            output_tokens,
            embedding_input_tokens,
            context_compaction_input_tokens,
            context_compaction_output_tokens,
        ]
    )
    if not total and image_input_units is None:
        return None
    return TokenUsageBreakdown(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        image_input_units=image_input_units,
        embedding_input_tokens=embedding_input_tokens,
        tool_call_count=tool_call_count,
        model_turn_count=model_turn_count,
        context_compaction_input_tokens=context_compaction_input_tokens,
        context_compaction_output_tokens=context_compaction_output_tokens,
        locally_estimated_total_tokens=total or None,
    )


def int_value(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if value in (None, ""):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            return parsed
    return None


def nested_dict(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = payload.get(key)
    return value if isinstance(value, dict) else None


def estimate_total_tokens(input_text: str, output_text: str) -> int | None:
    total = 0
    if input_text:
        total += estimate_tokens(input_text)
    if output_text:
        total += estimate_tokens(output_text)
    return total or None


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + TOKEN_CHAR_RATIO - 1) // TOKEN_CHAR_RATIO)


def estimate_tokens_from_chars(char_count: int) -> int | None:
    if char_count <= 0:
        return None
    return max(1, (char_count + TOKEN_CHAR_RATIO - 1) // TOKEN_CHAR_RATIO)


def endpoint_host_hash(base_url: str | None) -> str | None:
    if not base_url:
        return None
    parsed = urlparse(base_url)
    host = parsed.hostname or parsed.path.split("/", maxsplit=1)[0]
    if not host:
        return None
    return hashlib.sha256(host.encode("utf-8")).hexdigest()[:16]


def total_usage_tokens(breakdown: TokenUsageBreakdown) -> int:
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


def build_model_call_ledger_entry(
    *,
    run_id: str | None,
    project_id: str | None,
    role: ModelRole,
    config: ProviderConfig,
    metadata: ProviderRunMetadata,
    call_id: str | None = None,
    workflow_task_id: str | None = None,
    parent_call_id: str | None = None,
    prompt_version: str | None = None,
    structured_output_schema: str | None = None,
    request_artifact_ref: str | None = None,
    response_artifact_ref: str | None = None,
) -> ModelCallLedgerEntry:
    usage, source = normalize_token_usage(metadata.token_usage)
    return ModelCallLedgerEntry(
        id=call_id or f"{run_id or project_id}-{role.value}",
        project_id=project_id,
        run_id=run_id,
        workflow_task_id=workflow_task_id,
        parent_call_id=parent_call_id,
        role=role,
        provider=provider_kind_from_value(metadata.provider, config.provider),
        model=metadata.model or config.model,
        model_profile_id=optional_metadata_string(config, "model_profile_id"),
        endpoint_type=optional_metadata_string(config, "endpoint_type"),
        base_url_host_hash=endpoint_host_hash(config.base_url),
        deployment_id=optional_metadata_string(config, "deployment_id"),
        prompt_version=prompt_version,
        structured_output_schema=structured_output_schema,
        status=ModelCallStatus.FAILED if metadata.error else ModelCallStatus.COMPLETED,
        started_at=metadata.started_at,
        completed_at=metadata.completed_at,
        latency_ms=metadata.latency_ms,
        usage_source=source,
        usage=usage,
        request_artifact_ref=request_artifact_ref,
        response_artifact_ref=response_artifact_ref,
        error=metadata.error,
    )


def record_model_call_ledger_entry(entry: ModelCallLedgerEntry) -> ModelCallLedgerEntry:
    from guidesync_agent.storage import create_model_usage_store

    return create_model_usage_store().record(entry)


def provider_kind_from_value(value: str, fallback: ProviderKind) -> ProviderKind:
    try:
        return ProviderKind(value)
    except ValueError:
        return fallback


def optional_metadata_string(config: ProviderConfig, key: str) -> str | None:
    value = config.metadata.get(key)
    return value if isinstance(value, str) and value else None
