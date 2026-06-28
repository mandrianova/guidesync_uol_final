from __future__ import annotations

from guidesync_agent.schemas import AgentLoopToolCall, JsonValue


def string_arg(call: AgentLoopToolCall, name: str, default: str = "") -> str:
    return string_arg_from_mapping(call.arguments, name, default)


def optional_string_arg(call: AgentLoopToolCall, name: str) -> str | None:
    value = call.arguments.get(name)
    return value if isinstance(value, str) and value else None


def int_arg(call: AgentLoopToolCall, name: str, default: int) -> int:
    value = call.arguments.get(name)
    return value if isinstance(value, int) else default


def list_arg(call: AgentLoopToolCall, name: str) -> list[str]:
    return list_arg_from_mapping(call.arguments, name)


def string_arg_from_mapping(
    mapping: dict[str, JsonValue],
    name: str,
    default: str = "",
) -> str:
    value = mapping.get(name)
    return value if isinstance(value, str) else default


def list_arg_from_mapping(mapping: dict[str, JsonValue], name: str) -> list[str]:
    value = mapping.get(name)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def string_payload(payload: dict[str, JsonValue], name: str, default: str = "") -> str:
    value = payload.get(name)
    return value if isinstance(value, str) else default
