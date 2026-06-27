from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from typing import Any

from guidesync_agent.schemas import (
    LLMMessageRole,
    LLMMessageSource,
    LLMToolCallLink,
    LLMTranscriptMessage,
    ModelRole,
)
from guidesync_agent.services.model_usage import endpoint_host_hash

SECRET_KEY_PARTS = {
    "api_key",
    "authorization",
    "bearer",
    "cookie",
    "password",
    "secret",
    "token",
}


def pydantic_ai_transcript_payload(
    result: Any,
    *,
    prompt: str,
    prompt_metadata: Mapping[str, Any],
    tool_call_count: int,
) -> dict[str, Any]:
    messages = [
        {
            "role": LLMMessageRole.USER.value,
            "source": LLMMessageSource.PYDANTIC_AI.value,
            "content": prompt,
        }
    ]
    messages.extend(pydantic_ai_messages(result, "new_messages_json"))
    return {
        "source": LLMMessageSource.PYDANTIC_AI.value,
        "messages": messages,
        "prompt_metadata": dict(prompt_metadata),
        "tool_summary": {"tool_call_count": tool_call_count},
    }


def pydantic_ai_messages(result: Any, method_name: str) -> list[dict[str, Any]]:
    method = getattr(result, method_name, None)
    if not callable(method):
        return []
    try:
        raw = method()
    except Exception:  # noqa: BLE001 - transcript capture is best effort
        return []
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return [
                {
                    "role": LLMMessageRole.PROVIDER.value,
                    "source": LLMMessageSource.PYDANTIC_AI.value,
                    "content": raw,
                }
            ]
    else:
        parsed = raw
    items = parsed if isinstance(parsed, list) else [parsed]
    return [
        {
            "role": provider_message_role(item),
            "source": LLMMessageSource.PYDANTIC_AI.value,
            "content": json.dumps(item, ensure_ascii=False, default=str),
            "metadata": {"provider_message_type": provider_message_type(item)},
        }
        for item in items
    ]


def local_http_transcript_payload(
    *,
    system_prompt: str,
    user_prompt: str,
    request_payload: Mapping[str, Any],
    response_payload: Mapping[str, Any],
    output_text: str = "",
    prompt_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    messages = [
        {
            "role": LLMMessageRole.SYSTEM.value,
            "source": LLMMessageSource.LOCAL_HTTP.value,
            "content": system_prompt,
        },
        {
            "role": LLMMessageRole.USER.value,
            "source": LLMMessageSource.LOCAL_HTTP.value,
            "content": user_prompt,
        },
        {
            "role": LLMMessageRole.ASSISTANT.value,
            "source": LLMMessageSource.LOCAL_HTTP.value,
            "content": output_text,
            "metadata": {
                "provider_model": response_payload.get("model"),
                "response_id": response_payload.get("id"),
                "finish_reason": finish_reason(response_payload),
            },
        },
    ]
    return {
        "source": LLMMessageSource.LOCAL_HTTP.value,
        "messages": messages,
        "prompt_metadata": dict(prompt_metadata or {}),
        "provider_metadata": {
            "request": sanitize_secret_value(request_payload),
            "response": summarize_local_response(response_payload),
        },
    }


def transcript_messages(payload: Mapping[str, Any]) -> list[LLMTranscriptMessage]:
    messages = list_payload(payload, "messages")
    exchanges = list_payload(payload, "exchanges")
    for exchange in exchanges:
        if isinstance(exchange, Mapping):
            messages.extend(list_payload(exchange, "messages"))
    return [
        LLMTranscriptMessage(
            role=message_role(item.get("role") if isinstance(item, Mapping) else None),
            source=message_source(item.get("source") if isinstance(item, Mapping) else None),
            content=message_content(item),
            name=string_value(item.get("name")) if isinstance(item, Mapping) else None,
            metadata=mapping_payload(item, "metadata") if isinstance(item, Mapping) else {},
        )
        for item in messages
        if isinstance(item, Mapping)
    ]


def transcript_tool_calls(payload: Mapping[str, Any]) -> list[LLMToolCallLink]:
    items = list_payload(payload, "tool_calls")
    tool_summary = mapping_payload(payload, "tool_summary")
    items.extend(list_payload(tool_summary, "tool_calls"))
    return [
        LLMToolCallLink(
            name=string_value(item.get("name")) or "unknown",
            arguments_summary=mapping_payload(item, "arguments_summary"),
            result_status=string_value(item.get("result_status")) or "unknown",
            evidence_refs=string_list(item.get("evidence_refs")),
            artifact_refs=string_list(item.get("artifact_refs")),
        )
        for item in items
        if isinstance(item, Mapping)
    ]


def sanitize_secret_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            sanitized[key_text] = (
                "[REDACTED]" if is_secret_key(key_text) else sanitize_secret_value(item)
            )
        return sanitized
    if isinstance(value, list):
        return [sanitize_secret_value(item) for item in value]
    return value


def endpoint_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "endpoint_type": metadata.get("endpoint_type"),
        "base_url_host_hash": metadata.get("base_url_host_hash"),
        "deployment_id": metadata.get("deployment_id"),
    }
    base_url = metadata.get("base_url")
    if isinstance(base_url, str):
        result["base_url_host_hash"] = endpoint_host_hash(base_url)
    return {key: value for key, value in result.items() if value}


def model_settings(metadata: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "temperature",
        "top_p",
        "max_tokens",
        "max_output_tokens",
        "thinking",
        "response_format",
        "structured_output_mode",
    }
    return {key: value for key, value in metadata.items() if key in allowed}


def message_stats(messages: list[LLMTranscriptMessage]) -> dict[str, Any]:
    counts = Counter(message.role.value for message in messages)
    return {
        "by_role": dict(sorted(counts.items())),
        "content_chars": sum(len(message.content) for message in messages),
    }


def tool_call_count(
    payload: Mapping[str, Any],
    tool_calls: list[LLMToolCallLink],
) -> int:
    summary = mapping_payload(payload, "tool_summary")
    value = summary.get("tool_call_count") or payload.get("tool_call_count")
    if value is None:
        return len(tool_calls)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return len(tool_calls)
    return parsed if parsed >= 0 else len(tool_calls)


def is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SECRET_KEY_PARTS)


def message_role(value: object) -> LLMMessageRole:
    try:
        return LLMMessageRole(str(value))
    except ValueError:
        return LLMMessageRole.PROVIDER


def message_source(value: object) -> LLMMessageSource:
    try:
        return LLMMessageSource(str(value))
    except ValueError:
        return LLMMessageSource.NORMALIZED


def message_content(item: Mapping[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False, default=str)


def provider_message_role(item: object) -> str:
    if not isinstance(item, Mapping):
        return LLMMessageRole.PROVIDER.value
    kind = str(item.get("kind") or item.get("role") or item.get("type") or "").lower()
    if "request" in kind or "user" in kind:
        return LLMMessageRole.USER.value
    if "response" in kind or "assistant" in kind or "model" in kind:
        return LLMMessageRole.ASSISTANT.value
    if "system" in kind:
        return LLMMessageRole.SYSTEM.value
    if "tool" in kind:
        return LLMMessageRole.TOOL.value
    return LLMMessageRole.PROVIDER.value


def provider_message_type(item: object) -> str:
    if isinstance(item, Mapping):
        return str(item.get("kind") or item.get("type") or "")
    return type(item).__name__


def mapping_payload(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def list_payload(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return list(value) if isinstance(value, list) else []


def string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def finish_reason(response_payload: Mapping[str, Any]) -> str | None:
    choices = response_payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
        return string_value(choices[0].get("finish_reason"))
    return None


def summarize_local_response(response_payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": response_payload.get("id"),
        "model": response_payload.get("model"),
        "usage": response_payload.get("usage"),
        "stats": response_payload.get("stats"),
        "finish_reason": finish_reason(response_payload),
    }


def conversation_id_for(
    run_id: str | None,
    workflow_task_id: str | None,
    model_role: ModelRole,
) -> str:
    return ":".join(
        item
        for item in [
            run_id or "project-profile",
            workflow_task_id or "no-workflow-task",
            model_role.value,
        ]
        if item
    )
