from __future__ import annotations

import hashlib
from typing import Any, cast
from urllib.parse import urlparse

from guidesync_agent.schemas import TokenUsageBreakdown, TokenUsageSource
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
