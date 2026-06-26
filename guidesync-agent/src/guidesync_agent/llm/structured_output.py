from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel
from pydantic_ai import NativeOutput, PromptedOutput, ToolOutput

from guidesync_agent.schemas import (
    LocalHTTPChatEndpoint,
    ProviderConfig,
    ProviderKind,
    StructuredOutputCapabilities,
    StructuredOutputMode,
    StructuredOutputSelection,
)


def select_structured_output(
    config: ProviderConfig,
    output_model: type[BaseModel],
    *,
    requires_tools: bool,
) -> StructuredOutputSelection:
    capabilities = structured_output_capabilities(config)
    diagnostics: list[str] = []
    requested = requested_output_mode(config)
    native_allowed = capabilities.native_json_schema and (
        not requires_tools or capabilities.tool_native_compatible
    )

    if requested is StructuredOutputMode.NATIVE and not native_allowed:
        diagnostics.append("native structured output is unavailable for this step/provider")
        mode = (
            StructuredOutputMode.TOOL
            if requires_tools and capabilities.tool_output
            else (StructuredOutputMode.PROMPTED)
        )
    elif requested is StructuredOutputMode.TOOL and (
        not requires_tools or not capabilities.tool_output
    ):
        diagnostics.append("tool output is unavailable for this step/provider")
        mode = StructuredOutputMode.NATIVE if native_allowed else StructuredOutputMode.PROMPTED
    elif requested is not None:
        mode = requested
    elif requires_tools and capabilities.tool_output:
        mode = StructuredOutputMode.TOOL
    elif native_allowed:
        mode = StructuredOutputMode.NATIVE
    else:
        mode = StructuredOutputMode.PROMPTED

    schema = output_model.model_json_schema()
    return StructuredOutputSelection(
        mode=mode,
        schema_name=schema_name_for(output_model),
        schema_sha256=schema_sha256(schema),
        capabilities=capabilities,
        diagnostics=diagnostics,
    )


def structured_output_capabilities(config: ProviderConfig) -> StructuredOutputCapabilities:
    metadata = config.metadata
    if "structured_output_capabilities" in metadata:
        return StructuredOutputCapabilities.model_validate(
            metadata["structured_output_capabilities"]
        )

    native_default = default_native_json_schema_support(config)
    return StructuredOutputCapabilities(
        tool_output=config.provider == ProviderKind.PYDANTIC_AI,
        native_json_schema=metadata_bool(
            metadata,
            "supports_native_structured_output",
            default=native_default,
        ),
        prompted_output=True,
        tool_native_compatible=metadata_bool(
            metadata,
            "supports_tool_native_structured_output",
            default=False,
        ),
    )


def requested_output_mode(config: ProviderConfig) -> StructuredOutputMode | None:
    raw = config.metadata.get("structured_output_mode")
    if raw is None:
        return None
    return StructuredOutputMode(str(raw))


def default_native_json_schema_support(config: ProviderConfig) -> bool:
    if config.provider == ProviderKind.LOCAL_HTTP:
        return (
            local_http_endpoint_mode(config.base_url)
            is LocalHTTPChatEndpoint.OPENAI_CHAT_COMPLETIONS
        )
    if config.provider != ProviderKind.PYDANTIC_AI:
        return False
    if not config.model.startswith(("openai:", "openai-chat:", "openai-responses:")):
        return False
    return True


def pydantic_ai_output_type(
    output_model: type[BaseModel],
    selection: StructuredOutputSelection,
) -> Any:
    if selection.mode is StructuredOutputMode.NATIVE:
        return NativeOutput(output_model, name=selection.schema_name, strict=True)
    if selection.mode is StructuredOutputMode.PROMPTED:
        return PromptedOutput(output_model, name=selection.schema_name)
    return ToolOutput(output_model, name=selection.schema_name, strict=True)


def openai_json_schema_response_format(output_model: type[BaseModel]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name_for(output_model),
            "schema": output_model.model_json_schema(),
            "strict": True,
        },
    }


def prompted_schema_suffix(output_model: type[BaseModel]) -> str:
    schema = json.dumps(output_model.model_json_schema(), indent=2, sort_keys=True)
    return f"\n\nStructured output JSON schema generated from Pydantic:\n{schema}"


def schema_name_for(output_model: type[BaseModel]) -> str:
    name = output_model.__name__
    chars = [char.lower() if char.isalnum() else "_" for char in name]
    return "".join(chars).strip("_") or "structured_output"


def schema_sha256(schema: dict[str, Any]) -> str:
    payload = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def metadata_bool(metadata: dict[str, Any], key: str, *, default: bool) -> bool:
    raw = metadata.get(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on", "native"}
    return bool(raw)


def local_http_endpoint_mode(base_url: str | None) -> LocalHTTPChatEndpoint:
    if not base_url:
        return LocalHTTPChatEndpoint.CUSTOM_CHAT
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1") or normalized.endswith("/chat/completions"):
        return LocalHTTPChatEndpoint.OPENAI_CHAT_COMPLETIONS
    return LocalHTTPChatEndpoint.CUSTOM_CHAT
