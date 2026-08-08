from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from guidesync_agent.llm.structured_output import local_http_endpoint_mode
from guidesync_agent.schemas import (
    LocalHTTPChatEndpoint,
    ProviderConfig,
)


def post_local_chat(
    base_url: str,
    payload: dict[str, Any],
    timeout_seconds: int,
    api_key: str | None = None,
    *,
    endpoint: LocalHTTPChatEndpoint | None = None,
) -> dict[str, Any]:
    url = local_chat_url(base_url, endpoint)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(local_http_error_message(exc)) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Local model request failed: {exc}") from exc
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("Local model response must be a JSON object.")
    return parsed


def local_chat_url(
    base_url: str,
    endpoint: LocalHTTPChatEndpoint | None = None,
) -> str:
    mode = endpoint or local_http_endpoint_mode(base_url)
    normalized = base_url.rstrip("/")
    if mode is LocalHTTPChatEndpoint.OPENAI_CHAT_COMPLETIONS:
        if normalized.endswith("/chat/completions"):
            return normalized
        return f"{normalized}/chat/completions"
    return normalized


def local_chat_payload(
    config: ProviderConfig,
    system_prompt: str,
    input_text: str,
    *,
    endpoint: LocalHTTPChatEndpoint | None = None,
) -> dict[str, Any]:
    mode = endpoint or local_http_endpoint_mode(config.base_url)
    if mode is LocalHTTPChatEndpoint.OPENAI_CHAT_COMPLETIONS:
        return openai_chat_payload(config, system_prompt, input_text)
    return custom_chat_payload(config, system_prompt, input_text)


def openai_chat_payload(
    config: ProviderConfig,
    system_prompt: str,
    input_text: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": local_model_name(config.model),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_text},
        ],
        "temperature": 0,
    }
    apply_generation_settings(payload, config)
    if config.thinking is not None:
        payload["thinking"] = config.thinking
    return payload


def custom_chat_payload(
    config: ProviderConfig,
    system_prompt: str,
    input_text: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": local_model_name(config.model),
        "system_prompt": system_prompt,
        "input": input_text,
    }
    apply_generation_settings(payload, config)
    if config.thinking is not None:
        payload["thinking"] = config.thinking
    return payload


def apply_generation_settings(payload: dict[str, Any], config: ProviderConfig) -> None:
    if config.max_output_tokens is not None:
        payload["max_tokens"] = config.max_output_tokens
    if config.temperature is not None:
        payload["temperature"] = config.temperature


def local_model_name(model: str) -> str:
    if model.startswith(("openai:", "openai-chat:", "openai-responses:")):
        return model.split(":", maxsplit=1)[1]
    return model


def local_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            return content

    output = response.get("output")
    if isinstance(output, list):
        for item in reversed(output):
            if isinstance(item, dict) and item.get("type") == "message":
                content = item.get("content")
                if isinstance(content, str):
                    return content
    content = response.get("content") or response.get("message")
    if isinstance(content, str):
        return content
    raise RuntimeError("Local model response does not contain message content.")


def local_http_error_message(exc: HTTPError) -> str:
    body = ""
    try:
        body = exc.read().decode("utf-8")
    except Exception:  # noqa: BLE001 - HTTP body is best effort
        body = ""
    detail = ""
    if body:
        try:
            parsed = json.loads(body)
            error = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(error, dict):
                detail = str(error.get("message") or "")
            elif isinstance(parsed, dict):
                detail = str(parsed.get("message") or "")
        except json.JSONDecodeError:
            detail = body[:1000]
    if "context length" in detail.lower() or "n_keep" in detail.lower():
        return (
            "Local model context limit exceeded. The model server rejected the prompt because "
            f"it was larger than its configured context window. Details: {detail}"
        )
    suffix = f": {detail}" if detail else ""
    return f"Local model request failed: HTTP Error {exc.code} {exc.reason}{suffix}"
