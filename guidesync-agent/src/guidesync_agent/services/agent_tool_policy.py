from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from pathlib import PurePosixPath
from typing import Any

from guidesync_agent.schemas import (
    AgentContextTrustLevel,
    AgentLoopObservation,
    AgentLoopToolCall,
    AgentLoopToolName,
    AgentToolDefinition,
    AgentToolPermission,
    AgentToolResult,
    AgentToolResultStatus,
    AgentToolScope,
    AgentToolSideEffect,
)
from guidesync_agent.services.agent_tool_registry import (
    DEFAULT_TOOL_REGISTRY_ID,
    agent_loop_tool_definition,
)

ToolExecutor = Callable[[AgentLoopToolCall], AgentLoopObservation]


def guarded_agent_loop_executor(
    definitions: Mapping[AgentLoopToolName, AgentToolDefinition],
    executor: ToolExecutor,
) -> ToolExecutor:
    def execute(call: AgentLoopToolCall) -> AgentLoopObservation:
        return execute_with_policy(call, definitions, executor)

    return execute


def execute_with_policy(
    call: AgentLoopToolCall,
    definitions: Mapping[AgentLoopToolName, AgentToolDefinition],
    executor: ToolExecutor,
) -> AgentLoopObservation:
    definition = definitions.get(call.tool_name)
    if definition is None:
        return policy_observation(
            call,
            AgentToolResultStatus.UNSUPPORTED_TOOL,
            f"Unsupported tool for this workflow: {call.tool_name.value}",
        )
    if (
        definition.permission is not AgentToolPermission.READ_ONLY_ALLOWED
        or definition.side_effect is not AgentToolSideEffect.READ_ONLY
    ):
        return policy_observation(
            call,
            AgentToolResultStatus.DENIED,
            f"Tool is denied by read-only policy: {call.tool_name.value}",
        )
    invalid_reason = invalid_argument_reason(call.arguments, call.tool_name)
    if invalid_reason:
        return policy_observation(
            call,
            AgentToolResultStatus.INVALID_ARGUMENTS,
            invalid_reason,
        )

    started = time.perf_counter()
    try:
        observation = executor(call)
    except Exception as exc:  # noqa: BLE001 - model-facing tool errors become observations
        return policy_observation(
            call,
            AgentToolResultStatus.TOOL_ERROR,
            f"Tool failed: {exc}",
        )

    elapsed = time.perf_counter() - started
    if elapsed > definition.timeout_seconds:
        return policy_observation(
            call,
            AgentToolResultStatus.TIMEOUT,
            (
                f"Tool exceeded timeout {definition.timeout_seconds:.2f}s "
                f"after {elapsed:.2f}s: {call.tool_name.value}"
            ),
        )

    trusted = observation.model_copy(
        update={
            "result_status": (
                AgentToolResultStatus.SUCCESS
                if observation.ok
                else status_from_error_code(observation.error_code)
            ),
            "trust_level": trust_level_for_tool(call.tool_name),
            "payload": payload_with_policy(observation.payload, definition),
        }
    )
    if payload_size(trusted.payload) > definition.max_output_chars:
        return policy_observation(
            call,
            AgentToolResultStatus.TRUNCATED,
            f"Tool output exceeded {definition.max_output_chars} chars and was truncated.",
            payload={
                "truncated": True,
                "original_output_summary": trusted.output_summary,
                "max_output_chars": definition.max_output_chars,
            },
            evidence_refs=trusted.evidence_refs,
            artifact_ref=trusted.artifact_ref,
            trust_level=trusted.trust_level,
        )
    return trusted


def policy_result(observation: AgentLoopObservation) -> AgentToolResult:
    return AgentToolResult(
        status=observation.result_status,
        tool_name=observation.tool_name.value,
        ok=observation.ok,
        output_summary=observation.output_summary,
        payload=observation.payload,
        evidence_refs=observation.evidence_refs,
        artifact_ref=observation.artifact_ref,
        error_code=observation.error_code,
        error_message=observation.error_message,
        trust_level=observation.trust_level,
    )


VIRTUAL_PATH_TOOL_NAMES = {
    AgentLoopToolName.LIST_DIRECTORY,
    AgentLoopToolName.LIST_DIRECTORY_WITH_SIZES,
    AgentLoopToolName.DIRECTORY_TREE,
    AgentLoopToolName.SEARCH_FILES,
    AgentLoopToolName.READ_TEXT_FILE,
    AgentLoopToolName.READ_MULTIPLE_FILES,
    AgentLoopToolName.GET_FILE_INFO,
}


def invalid_argument_reason(
    arguments: Mapping[str, Any],
    tool_name: AgentLoopToolName,
) -> str | None:
    allow_virtual_paths = tool_name in VIRTUAL_PATH_TOOL_NAMES
    for key, value in arguments.items():
        if key in {"path", "document_path"} and unsafe_path(
            value,
            allow_virtual_path=allow_virtual_paths and key == "path",
        ):
            return f"Path argument is outside the allowed repository scope: {key}"
        if key == "paths":
            paths = value if isinstance(value, list) else []
            if any(unsafe_path(item, allow_virtual_path=allow_virtual_paths) for item in paths):
                return "One path argument is outside the allowed repository scope."
        if key == "path_filters":
            filters = value if isinstance(value, list) else []
            if any(unsafe_path(item) for item in filters):
                return "Path filter is outside the allowed repository scope."
        if key == "excludePatterns":
            patterns = value if isinstance(value, list) else []
            if any(unsafe_path(item) for item in patterns):
                return "Exclude pattern is outside the allowed repository scope."
    return None


def unsafe_path(value: object, *, allow_virtual_path: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.replace("\\", "/")
    if "\x00" in normalized:
        return True
    if normalized.startswith("/"):
        if allow_virtual_path and normalized.startswith("/repositories/"):
            parts = PurePosixPath(normalized).parts
            return any(part == ".." for part in parts)
        return True
    if normalized.startswith("\\"):
        return True
    parts = PurePosixPath(normalized).parts
    return any(part == ".." for part in parts)


def status_from_error_code(error_code: str | None) -> AgentToolResultStatus:
    if error_code == AgentToolResultStatus.UNSUPPORTED_TOOL.value:
        return AgentToolResultStatus.UNSUPPORTED_TOOL
    if error_code == AgentToolResultStatus.INVALID_ARGUMENTS.value:
        return AgentToolResultStatus.INVALID_ARGUMENTS
    if error_code == AgentToolResultStatus.DENIED.value:
        return AgentToolResultStatus.DENIED
    if error_code == AgentToolResultStatus.TIMEOUT.value:
        return AgentToolResultStatus.TIMEOUT
    return AgentToolResultStatus.TOOL_ERROR


def payload_size(payload: dict[str, Any]) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    except TypeError:
        return len(str(payload))


def payload_with_policy(
    payload: dict[str, Any],
    definition: AgentToolDefinition,
) -> dict[str, Any]:
    return {
        **payload,
        "_tool_policy": {
            "registry_id": DEFAULT_TOOL_REGISTRY_ID,
            "permission": definition.permission.value,
            "side_effect": definition.side_effect.value,
            "scope": definition.scope.value,
            "risk": definition.risk.value,
        },
        "_trust_level": trust_level_for_definition(definition).value,
    }


def policy_observation(
    call: AgentLoopToolCall,
    status: AgentToolResultStatus,
    message: str,
    *,
    payload: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
    artifact_ref: str | None = None,
    trust_level: AgentContextTrustLevel = AgentContextTrustLevel.TOOL_STATUS,
) -> AgentLoopObservation:
    return AgentLoopObservation(
        tool_name=call.tool_name,
        arguments=call.arguments,
        ok=False,
        result_status=status,
        trust_level=trust_level,
        output_summary=message,
        payload=payload or {"tool_result_status": status.value},
        evidence_refs=evidence_refs or [],
        artifact_ref=artifact_ref,
        error_code=status.value,
        error_message=message,
    )


def trust_level_for_tool(name: AgentLoopToolName) -> AgentContextTrustLevel:
    return trust_level_for_definition(agent_loop_tool_definition(name))


def trust_level_for_definition(definition: AgentToolDefinition) -> AgentContextTrustLevel:
    if definition.scope is AgentToolScope.RAW_DIFF:
        return AgentContextTrustLevel.UNTRUSTED_DIFF
    if definition.scope is AgentToolScope.KNOWLEDGE_BASE:
        return AgentContextTrustLevel.UNTRUSTED_KNOWLEDGE
    if definition.scope is AgentToolScope.BROWSER_READ:
        return AgentContextTrustLevel.UNTRUSTED_BROWSER
    if definition.scope in {AgentToolScope.REPOSITORY_CACHE, AgentToolScope.PROJECT_PROFILE}:
        return AgentContextTrustLevel.UNTRUSTED_REPOSITORY
    return AgentContextTrustLevel.TOOL_STATUS
