from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.messages import (
    FinalResultEvent,
    ModelRequest,
    ModelResponse,
    OutputToolCallEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    ToolCallPart,
    ToolCallPartDelta,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext, ModelRequestParameters
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel
from storage_test_utils import sqlite_database_url

from guidesync_agent.agent_runtime import pydantic_ai as pydantic_agent_runtime
from guidesync_agent.agent_runtime import pydantic_ai_context
from guidesync_agent.agent_runtime.pydantic_ai_context import (
    CONTEXT_SUMMARY_PREFIX,
    PydanticAIContextGuard,
    bounded_tool_result,
)
from guidesync_agent.agent_runtime.transcripts import read_transcript_artifact
from guidesync_agent.schemas import (
    AgentExecutionLimits,
    LLMTranscriptEventKind,
    ModelRole,
    ProviderConfig,
    ProviderKind,
)


class RuntimeOutput(BaseModel):
    answer: str


@dataclass
class RuntimeDeps:
    tool_calls: int = 0


def test_runtime_replaces_legacy_agent_limits_with_global_policy() -> None:
    legacy = ProviderConfig(
        execution_limits=AgentExecutionLimits(
            request_limit=12,
            tool_calls_limit=20,
        )
    )

    configured = pydantic_agent_runtime.with_global_agent_execution_limits(legacy)

    assert configured.execution_limits.request_limit == 200
    assert configured.execution_limits.tool_calls_limit == 200


def model_request_context(messages) -> ModelRequestContext:
    return ModelRequestContext(
        model=TestModel(),
        messages=messages,
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )


def model_visible_user_text(request: ModelRequest) -> str:
    return "\n".join(
        part.content
        for part in request.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, str)
    )


def test_context_guard_is_noop_below_budget() -> None:
    summary_called = False

    async def summarize(_messages, _request_context):
        nonlocal summary_called
        summary_called = True
        return "unused", {}

    messages = [ModelRequest.user_text_prompt("Keep this task objective.")]
    context = model_request_context(messages)
    guard = PydanticAIContextGuard(
        context_budget_tokens=10_000,
        tool_result_char_limit=1_000,
        summary_builder=summarize,
    )

    result = asyncio.run(guard.before_model_request(cast(Any, None), context))

    assert result.messages == messages
    assert guard.state.compaction_count == 0
    assert summary_called is False


def test_context_guard_compacts_before_next_model_request_and_rehydrates_state() -> None:
    async def summarize(_messages, _request_context):
        return (
            "Objective: finish the report. Durable coverage: 25/100. "
            "Evidence: diff:repo:src/app.py:base:head. Next: list uncovered inventory.",
            {"input_tokens": 900, "output_tokens": 80},
        )

    raw_tool_tail = "raw tool payload " * 300
    messages = [
        ModelRequest.user_text_prompt("Keep exact user constraint: do not stop the run."),
        ModelResponse(parts=[TextPart(raw_tool_tail)]),
        ModelRequest.user_text_prompt("Continue inside the same agent loop."),
    ]
    context = model_request_context(messages)
    guard = PydanticAIContextGuard(
        context_budget_tokens=1_000,
        tool_result_char_limit=1_000,
        summary_builder=summarize,
    )

    result = asyncio.run(guard.before_model_request(cast(Any, None), context))

    assert len(result.messages) == 1
    compacted_request = cast(ModelRequest, result.messages[0])
    visible_text = model_visible_user_text(compacted_request)
    assert "Keep exact user constraint" in visible_text
    assert "Continue inside the same agent loop" in visible_text
    assert CONTEXT_SUMMARY_PREFIX in visible_text
    assert "Durable coverage: 25/100" in visible_text
    assert "diff:repo:src/app.py:base:head" in visible_text
    assert raw_tool_tail not in visible_text
    assert guard.state.compaction_count == 1
    assert guard.state.compacted_message_count == 3
    assert guard.state.context_compaction_input_tokens == 900
    assert guard.state.context_compaction_output_tokens == 80


def test_oversized_tool_result_has_hard_cap_and_focused_reread_hint() -> None:
    bounded, truncated = bounded_tool_result(
        {"content": "large result " * 1_000},
        tool_name="read_change_diff",
        char_limit=800,
    )

    assert truncated is True
    assert isinstance(bounded, str)
    assert len(bounded) <= 800
    assert "tool result truncated" in bounded
    assert "read_change_diff" in bounded
    assert "offset/limit" in bounded


def test_stream_consumption_stops_at_final_result(monkeypatch) -> None:
    final_result = object()
    recorded = []

    class FinalEvent:
        result = final_result

    class Recorder:
        def record_pydantic_event(self, event) -> None:
            recorded.append(event)

    async def events():
        yield "progress"
        yield FinalEvent()
        raise AssertionError("events after the final result must not be consumed")

    monkeypatch.setattr(pydantic_agent_runtime, "AgentRunResultEvent", FinalEvent)

    result = asyncio.run(pydantic_agent_runtime.consume_stream_events(events(), Recorder()))

    assert result is final_result
    assert recorded == ["progress"]


def test_native_stream_stops_when_structured_output_is_valid() -> None:
    recorded = []

    class TextPart:
        part_kind = "text"
        content = '{"answer":'

    class TextDelta:
        part_delta_kind = "text"
        content_delta = '"done"}'

    class StartEvent:
        event_kind = "part_start"
        index = 0
        part = TextPart()

    class DeltaEvent:
        event_kind = "part_delta"
        index = 0
        delta = TextDelta()

    class Recorder:
        def record_pydantic_event(self, event) -> None:
            recorded.append(event)

    async def events():
        yield StartEvent()
        yield DeltaEvent()
        raise AssertionError("events after valid structured output must not be consumed")

    result = asyncio.run(
        pydantic_agent_runtime.consume_stream_events(
            events(),
            Recorder(),
            early_output_model=RuntimeOutput,
        )
    )

    assert result == RuntimeOutput(answer="done")
    assert len(recorded) == 2


def test_native_output_tool_stream_stops_at_final_snapshot() -> None:
    recorded = []
    output_tool_name = "runtimeoutput"
    tool_call_id = "output-call-1"

    class Recorder:
        def record_pydantic_event(self, event) -> None:
            recorded.append(event)

    async def events():
        yield PartStartEvent(
            index=0,
            part=ToolCallPart(output_tool_name, '{"answer":', tool_call_id),
        )
        yield FinalResultEvent(tool_name=output_tool_name, tool_call_id=tool_call_id)
        yield PartDeltaEvent(
            index=0,
            delta=ToolCallPartDelta(args_delta='"done"}'),
        )
        raise AssertionError("events after the valid output-tool snapshot must not be consumed")

    result = asyncio.run(
        pydantic_agent_runtime.consume_stream_events(
            events(),
            Recorder(),
            early_output_model=RuntimeOutput,
        )
    )

    assert result == RuntimeOutput(answer="done")
    assert len(recorded) == 3


def test_native_output_tool_event_completes_payload_after_final_snapshot() -> None:
    recorded = []
    output_tool_name = "runtimeoutput"
    tool_call_id = "output-call-1"

    class Recorder:
        def record_pydantic_event(self, event) -> None:
            recorded.append(event)

    async def events():
        yield FinalResultEvent(tool_name=output_tool_name, tool_call_id=tool_call_id)
        yield OutputToolCallEvent(
            ToolCallPart(output_tool_name, {"answer": "done"}, tool_call_id)
        )
        raise AssertionError("events after the complete output-tool call must not be consumed")

    result = asyncio.run(
        pydantic_agent_runtime.consume_stream_events(
            events(),
            Recorder(),
            early_output_model=RuntimeOutput,
        )
    )

    assert result == RuntimeOutput(answer="done")
    assert len(recorded) == 2


def test_stream_consumer_cleans_up_child_tasks_when_deadline_cancels(monkeypatch) -> None:
    async def scenario() -> None:
        stream_started = asyncio.Event()
        stream_closed = asyncio.Event()
        wait_forever = asyncio.Event()

        class HangingAgent:
            @asynccontextmanager
            async def run_stream_events(self, *_args, **_kwargs):
                async def events():
                    try:
                        stream_started.set()
                        await wait_forever.wait()
                        if False:
                            yield None
                    finally:
                        stream_closed.set()

                yield events()

        class Recorder:
            def record_pydantic_event(self, _event) -> None:
                return None

        async def wait_for_cancellation(_task_id: str) -> None:
            await wait_forever.wait()

        monkeypatch.setattr(
            pydantic_agent_runtime,
            "wait_for_workflow_cancellation",
            wait_for_cancellation,
        )
        request = pydantic_agent_runtime.PydanticAgentRunRequest(
            prompt="Wait.",
            instructions="Wait.",
            output_model=RuntimeOutput,
            deps=RuntimeDeps(),
            deps_type=RuntimeDeps,
            config=ProviderConfig(),
            model_role=ModelRole.ORCHESTRATOR,
            workflow_task_id="workflow-timeout",
        )
        task = asyncio.create_task(
            pydantic_agent_runtime.consume_agent_stream(
                cast(Any, HangingAgent()),
                request,
                cast(Any, Recorder()),
                UsageLimits(),
            )
        )
        await stream_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream_closed.is_set()

    asyncio.run(scenario())


def test_runtime_timeout_has_an_actionable_deadline_message(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = sqlite_database_url(tmp_path / "runtime-timeout.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setattr(
        pydantic_agent_runtime,
        "build_pydantic_ai_model",
        lambda _config: TestModel(custom_output_args={"answer": "unused"}),
    )

    async def hang_until_cancelled(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(
        pydantic_agent_runtime,
        "consume_agent_stream",
        hang_until_cancelled,
    )
    request = pydantic_agent_runtime.PydanticAgentRunRequest(
        prompt="Wait forever.",
        instructions="Wait forever.",
        output_model=RuntimeOutput,
        deps=RuntimeDeps(),
        deps_type=RuntimeDeps,
        config=ProviderConfig(
            execution_limits=AgentExecutionLimits(total_timeout_seconds=1),
        ),
        model_role=ModelRole.ORCHESTRATOR,
        workflow_task_id="workflow-timeout-message",
    )

    with pytest.raises(
        TimeoutError,
        match="Pydantic AI runtime exceeded total deadline of 1 seconds",
    ):
        asyncio.run(pydantic_agent_runtime.run_pydantic_agent(request))


def test_nested_agent_run_can_skip_parent_concurrency_slot(monkeypatch, tmp_path: Path) -> None:
    database_url = sqlite_database_url(tmp_path / "nested-runtime.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    entered_slot = False

    @asynccontextmanager
    async def record_slot(_config):
        nonlocal entered_slot
        entered_slot = True
        yield

    monkeypatch.setattr(pydantic_agent_runtime.agent_concurrency_limiter, "slot", record_slot)
    monkeypatch.setattr(
        pydantic_agent_runtime,
        "build_pydantic_ai_model",
        lambda _config: TestModel(custom_output_args={"answer": "nested done"}),
    )

    result = pydantic_agent_runtime.run_pydantic_agent_sync(
        pydantic_agent_runtime.PydanticAgentRunRequest(
            prompt="Return the nested result.",
            instructions="Return one structured result.",
            output_model=RuntimeOutput,
            deps=RuntimeDeps(),
            deps_type=RuntimeDeps,
            config=ProviderConfig(
                provider=ProviderKind.PYDANTIC_AI,
                model="openai-chat:test-model",
            ),
            model_role=ModelRole.SCREENSHOT_VISION,
            acquire_concurrency_slot=False,
        )
    )

    assert RuntimeOutput.model_validate(result.output).answer == "nested done"
    assert entered_slot is False


def test_pydantic_agent_runtime_persists_tool_events_to_db(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = sqlite_database_url(tmp_path / "runtime-transcripts.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setattr(
        pydantic_agent_runtime,
        "build_pydantic_ai_model",
        lambda _config: TestModel(
            call_tools=["echo_tool"],
            custom_output_args={"answer": "done"},
        ),
    )

    def register_tools(agent: Agent[RuntimeDeps, RuntimeOutput]) -> None:
        @agent.tool
        def echo_tool(ctx: RunContext[RuntimeDeps], value: str = "hello") -> dict[str, str]:
            """Echo a value through a deterministic test tool."""
            ctx.deps.tool_calls += 1
            return {"echo": value}

    result = pydantic_agent_runtime.run_pydantic_agent_sync(
        pydantic_agent_runtime.PydanticAgentRunRequest(
            prompt="Use the echo tool and return done.",
            instructions="Call the tool once.",
            output_model=RuntimeOutput,
            deps=RuntimeDeps(),
            deps_type=RuntimeDeps,
            config=ProviderConfig(
                provider=ProviderKind.PYDANTIC_AI,
                model="openai-chat:test-model",
            ),
            model_role=ModelRole.ORCHESTRATOR,
            project_id="project-runtime",
            run_id="run-runtime",
            workflow_task_id="task-runtime",
            register_tools=register_tools,
        ),
    )

    loaded = read_transcript_artifact(result.transcript_id or "")

    assert RuntimeOutput.model_validate(result.output).answer == "done"
    assert loaded is not None
    assert loaded.status == "completed"
    event_kinds = [event.event_kind for event in loaded.events]
    assert event_kinds[0] == LLMTranscriptEventKind.MODEL_REQUEST
    assert event_kinds.count(LLMTranscriptEventKind.TOOL_CALL) == 2
    assert event_kinds.count(LLMTranscriptEventKind.TOOL_RESULT) == 2
    assert event_kinds.count(LLMTranscriptEventKind.FINAL_SNAPSHOT) >= 1
    assert loaded.tool_calls[0].name == "echo_tool"


def test_pydantic_agent_runtime_supports_plain_text_with_tools(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = sqlite_database_url(tmp_path / "runtime-text-output.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setattr(
        pydantic_agent_runtime,
        "build_pydantic_ai_model",
        lambda _config: TestModel(
            call_tools=["save_artifact"],
            custom_output_text="Saved one analysis artifact.",
        ),
    )

    def register_tools(agent: Agent[RuntimeDeps, str]) -> None:
        @agent.tool
        def save_artifact(ctx: RunContext[RuntimeDeps]) -> dict[str, str]:
            """Save one deterministic analysis artifact."""
            ctx.deps.tool_calls += 1
            return {"status": "saved", "artifact_id": "artifact-1"}

    result = pydantic_agent_runtime.run_pydantic_agent_sync(
        pydantic_agent_runtime.PydanticAgentRunRequest(
            prompt="Inspect the changes and save the result.",
            instructions="Use the artifact tool, then summarize in plain text.",
            output_model=None,
            deps=RuntimeDeps(),
            deps_type=RuntimeDeps,
            config=ProviderConfig(
                provider=ProviderKind.PYDANTIC_AI,
                model="openai-chat:test-model",
            ),
            model_role=ModelRole.CODE_CHANGE_ANALYSIS,
            project_id="project-runtime",
            run_id="run-runtime",
            workflow_task_id="task-runtime",
            register_tools=register_tools,
        )
    )

    loaded = read_transcript_artifact(result.transcript_id or "")
    assert result.output == "Saved one analysis artifact."
    assert result.usage["code_change_analysis_structured_output_mode"] == "text"
    assert loaded is not None
    assert loaded.tool_calls[0].name == "save_artifact"


def test_agent_loop_total_output_limit_is_separate_from_per_response_limit() -> None:
    config = ProviderConfig(max_output_tokens=4_096)
    request = pydantic_agent_runtime.PydanticAgentRunRequest(
        prompt="Analyze all inventory pages.",
        instructions="Continue the bounded tool loop.",
        output_model=None,
        deps=RuntimeDeps(),
        deps_type=RuntimeDeps,
        config=config,
        model_role=ModelRole.CODE_CHANGE_ANALYSIS,
        total_output_tokens_limit=64_000,
    )

    assert pydantic_agent_runtime.agent_total_output_tokens_limit(request, config) == 64_000
    assert pydantic_agent_runtime.model_settings_from_provider(config) == {
        "max_tokens": 4_096
    }


def test_runtime_compacts_between_tool_turns_inside_one_agent_run(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = sqlite_database_url(tmp_path / "runtime-compaction.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    model_calls = 0

    async def model_stream(_messages, agent_info):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            yield {
                0: DeltaToolCall(
                    name="large_echo",
                    json_args="{}",
                    tool_call_id="large-echo-1",
                )
            }
            return
        yield {
            0: DeltaToolCall(
                name=agent_info.output_tools[0].name,
                json_args='{"answer":"done"}',
                tool_call_id="runtime-output-1",
            )
        }

    monkeypatch.setattr(
        pydantic_agent_runtime,
        "build_pydantic_ai_model",
        lambda _config: FunctionModel(stream_function=model_stream),
    )

    async def summarize(_messages, _request_context):
        return "Tool completed. Continue to the final structured output.", {
            "input_tokens": 700,
            "output_tokens": 20,
        }

    monkeypatch.setattr(
        pydantic_ai_context,
        "summarize_with_active_model",
        summarize,
    )

    def register_tools(agent: Agent[RuntimeDeps, RuntimeOutput]) -> None:
        @agent.tool
        def large_echo(ctx: RunContext[RuntimeDeps]) -> dict[str, str]:
            """Return a deliberately large result for runtime compaction."""
            ctx.deps.tool_calls += 1
            return {"content": "large tool observation " * 400}

    result = pydantic_agent_runtime.run_pydantic_agent_sync(
        pydantic_agent_runtime.PydanticAgentRunRequest(
            prompt="Use the tool once, then return done.",
            instructions="Call the tool before returning the structured result.",
            output_model=RuntimeOutput,
            deps=RuntimeDeps(),
            deps_type=RuntimeDeps,
            config=ProviderConfig(
                provider=ProviderKind.PYDANTIC_AI,
                model="openai-chat:test-model",
            ),
            model_role=ModelRole.ORCHESTRATOR,
            register_tools=register_tools,
            context_budget_tokens=500,
            tool_result_char_limit=2_000,
        )
    )

    assert RuntimeOutput.model_validate(result.output).answer == "done"
    assert result.usage["requests"] == 2
    assert result.usage["context_compaction_count"] == 1
    assert result.usage["context_compacted_message_count"] == 3
    assert result.usage["context_compaction_input_tokens"] == 700
    assert result.usage["tool_result_truncation_count"] == 1
    assert model_calls == 2
