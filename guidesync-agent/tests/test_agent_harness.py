from __future__ import annotations

import time

from guidesync_agent.agent_runtime.context_compaction import summarize_observations
from guidesync_agent.schemas import (
    AgentLoopObservation,
    AgentLoopToolCall,
    AgentLoopToolName,
    AgentToolPermission,
    AgentToolResultStatus,
    AgentToolSideEffect,
)
from guidesync_agent.tools.code_change_agent import (
    code_change_tool_definitions,
    register_code_change_agent_tools,
)
from guidesync_agent.tools.policy import execute_with_policy, policy_result
from guidesync_agent.tools.registry import (
    agent_loop_tool_definition,
)


def test_tool_definitions_include_read_only_policy_metadata() -> None:
    definitions = code_change_tool_definitions()

    assert definitions[AgentLoopToolName.READ_TEXT_FILE].permission == (
        AgentToolPermission.READ_ONLY_ALLOWED
    )
    assert definitions[AgentLoopToolName.READ_TEXT_FILE].side_effect == (
        AgentToolSideEffect.READ_ONLY
    )
    assert definitions[AgentLoopToolName.READ_RAW_DIFF].permission == (
        AgentToolPermission.READ_ONLY_ALLOWED
    )
    assert definitions[AgentLoopToolName.SEARCH_KNOWLEDGE_BASE].audit_summary


def test_code_change_agent_tools_register_with_pydantic_ai() -> None:
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    agent = Agent(TestModel(), output_type=str)

    register_code_change_agent_tools(agent)


def test_policy_denies_unsupported_tool_for_workflow() -> None:
    call = AgentLoopToolCall(tool_name=AgentLoopToolName.SEARCH_KNOWLEDGE_BASE)

    observation = execute_with_policy(
        call,
        {
            AgentLoopToolName.READ_TEXT_FILE: agent_loop_tool_definition(
                AgentLoopToolName.READ_TEXT_FILE
            )
        },
        lambda _: AgentLoopObservation(tool_name=call.tool_name),
    )

    assert observation.result_status == AgentToolResultStatus.UNSUPPORTED_TOOL
    assert policy_result(observation).status == AgentToolResultStatus.UNSUPPORTED_TOOL


def test_policy_rejects_path_traversal_arguments() -> None:
    call = AgentLoopToolCall(
        tool_name=AgentLoopToolName.READ_TEXT_FILE,
        arguments={"path": "../secrets.env"},
    )

    observation = execute_with_policy(
        call,
        {call.tool_name: agent_loop_tool_definition(call.tool_name)},
        lambda _: AgentLoopObservation(tool_name=call.tool_name),
    )

    assert observation.result_status == AgentToolResultStatus.INVALID_ARGUMENTS


def test_policy_allows_virtual_repository_paths_for_filesystem_tools() -> None:
    call = AgentLoopToolCall(
        tool_name=AgentLoopToolName.READ_TEXT_FILE,
        arguments={"path": "/repositories/repo/docs/guide.md"},
    )

    observation = execute_with_policy(
        call,
        {call.tool_name: agent_loop_tool_definition(call.tool_name)},
        lambda _: AgentLoopObservation(tool_name=call.tool_name, payload={"content": "ok"}),
    )

    assert observation.result_status == AgentToolResultStatus.SUCCESS


def test_policy_surfaces_tool_error_timeout_and_truncation() -> None:
    call = AgentLoopToolCall(tool_name=AgentLoopToolName.READ_TEXT_FILE)
    definition = agent_loop_tool_definition(call.tool_name)

    error_observation = execute_with_policy(
        call,
        {call.tool_name: definition},
        lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert error_observation.result_status == AgentToolResultStatus.TOOL_ERROR

    timeout_observation = execute_with_policy(
        call,
        {call.tool_name: definition.model_copy(update={"timeout_seconds": 0.001})},
        lambda _: slow_observation(call),
    )
    assert timeout_observation.result_status == AgentToolResultStatus.TIMEOUT

    truncated_observation = execute_with_policy(
        call,
        {call.tool_name: definition.model_copy(update={"max_output_chars": 10})},
        lambda _: AgentLoopObservation(
            tool_name=call.tool_name,
            payload={"content": "x" * 100},
        ),
    )
    assert truncated_observation.result_status == AgentToolResultStatus.TRUNCATED


def test_compaction_summary_preserves_policy_state() -> None:
    observation = AgentLoopObservation(
        tool_name=AgentLoopToolName.READ_TEXT_FILE,
        result_status=AgentToolResultStatus.DENIED,
        ok=False,
        output_summary="denied by policy",
    )

    summary = summarize_observations([observation])

    assert "Read-only tool policy" in summary
    assert "denied" in summary


def slow_observation(call: AgentLoopToolCall) -> AgentLoopObservation:
    time.sleep(0.01)
    return AgentLoopObservation(tool_name=call.tool_name)
