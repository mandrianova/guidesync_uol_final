from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterable, Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field, is_dataclass
from inspect import isawaitable
from typing import Any, Protocol, cast

from pydantic import BaseModel, ValidationError
from pydantic_ai import Agent, AgentRunResultEvent, UsageLimits
from pydantic_ai.messages import UserContent
from pydantic_ai.settings import ModelSettings as AgentModelSettings

from guidesync_agent.agent_runtime.concurrency import agent_concurrency_limiter
from guidesync_agent.agent_runtime.pydantic_ai_context import (
    DEFAULT_CONTEXT_BUDGET_TOKENS,
    DEFAULT_TOOL_RESULT_CHAR_LIMIT,
    PydanticAIContextGuard,
)
from guidesync_agent.agent_runtime.transcript_recorder import LLMTranscriptRecorder
from guidesync_agent.agent_runtime.transcript_types import LLMTranscriptContext
from guidesync_agent.llm.factory import (
    build_pydantic_ai_model,
    pydantic_ai_generation_config,
)
from guidesync_agent.llm.structured_output import (
    pydantic_ai_output_type,
    select_structured_output,
)
from guidesync_agent.schemas import (
    ModelRole,
    ProjectWorkflowTaskStatus,
    ProviderConfig,
    StructuredOutputMode,
    StructuredOutputSelection,
)
from guidesync_agent.storage import create_project_workflow_store

ToolRegistrar = Callable[[Agent[Any, Any]], None]


class PydanticEventRecorder(Protocol):
    def record_pydantic_event(self, event: Any) -> None: ...


class PydanticAgentRunCancelledError(RuntimeError):
    pass


@dataclass
class PydanticAgentRuntimeResult:
    output: BaseModel | str
    usage: dict[str, Any]
    transcript_id: str | None
    raw_result: Any


@dataclass
class EarlyOutputToolState:
    streamed_parts: dict[int, Any] = field(default_factory=dict)
    completed_parts: dict[str, Any] = field(default_factory=dict)
    tool_name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class PydanticAgentLaunchContext:
    config: ProviderConfig
    structured_output: StructuredOutputSelection | None
    model: Any
    context_guard: PydanticAIContextGuard


@dataclass(frozen=True)
class PydanticAgentRunRequest[DepsT]:
    prompt: str | Sequence[UserContent]
    instructions: str
    output_model: type[BaseModel] | None
    deps: DepsT
    deps_type: type[DepsT]
    config: ProviderConfig
    model_role: ModelRole
    project_id: str | None = None
    run_id: str | None = None
    workflow_task_id: str | None = None
    model_call_id: str | None = None
    token_ledger_entry_id: str | None = None
    prompt_metadata: Mapping[str, Any] | None = None
    register_tools: ToolRegistrar | None = None
    retries: int | None = None
    requires_tools: bool = True
    allow_early_output: bool = True
    acquire_concurrency_slot: bool = True
    context_budget_tokens: int = DEFAULT_CONTEXT_BUDGET_TOKENS
    tool_result_char_limit: int = DEFAULT_TOOL_RESULT_CHAR_LIMIT


async def run_pydantic_agent[DepsT](
    request: PydanticAgentRunRequest[DepsT],
) -> PydanticAgentRuntimeResult:
    config = pydantic_ai_generation_config(request.config)
    concurrency_context = (
        agent_concurrency_limiter.slot(config)
        if request.acquire_concurrency_slot
        else nullcontext()
    )
    async with concurrency_context:
        model = build_pydantic_ai_model(config)
        structured_output = (
            select_structured_output(
                config,
                request.output_model,
                requires_tools=request.requires_tools,
            )
            if request.output_model is not None
            else None
        )
        recorder = LLMTranscriptRecorder(
            LLMTranscriptContext(
                project_id=request.project_id,
                run_id=request.run_id,
                workflow_task_id=request.workflow_task_id,
                model_role=request.model_role,
                provider=config.provider,
                model=config.model,
                metadata={
                    **config.metadata,
                    "provider": config.provider.value,
                    "model": config.model,
                    "base_url": config.base_url,
                    "timeout_seconds": config.timeout_seconds,
                    "max_concurrent_agents": config.max_concurrent_agents,
                    "thinking": config.thinking,
                    "prompt_metadata": dict(request.prompt_metadata or {}),
                },
                model_call_id=request.model_call_id,
                token_ledger_entry_id=request.token_ledger_entry_id,
                endpoint_type=config.metadata.get("endpoint_type")
                if isinstance(config.metadata.get("endpoint_type"), str)
                else None,
            )
        )
        recorder.start(initial_prompt=transcript_prompt_text(request.prompt))
        limits = config.execution_limits
        context_guard = PydanticAIContextGuard(
            context_budget_tokens=request.context_budget_tokens,
            tool_result_char_limit=request.tool_result_char_limit,
        )
        agent = cast(
            Agent[DepsT, Any],
            Agent(
                model,
                output_type=(
                    pydantic_ai_output_type(request.output_model, structured_output)
                    if request.output_model is not None and structured_output is not None
                    else str
                ),
                instructions=request.instructions,
                deps_type=request.deps_type,
                model_settings=model_settings_from_provider(config),
                retries=request.retries if request.retries is not None else limits.retries,
                capabilities=[context_guard.capability()],
            ),
        )
        if request.register_tools is not None:
            request.register_tools(agent)
        return await execute_pydantic_agent_launch(
            agent,
            request,
            recorder,
            PydanticAgentLaunchContext(
                config=config,
                structured_output=structured_output,
                model=model,
                context_guard=context_guard,
            ),
        )


async def execute_pydantic_agent_launch[DepsT](
    agent: Agent[DepsT, Any],
    request: PydanticAgentRunRequest[DepsT],
    recorder: LLMTranscriptRecorder,
    launch: PydanticAgentLaunchContext,
) -> PydanticAgentRuntimeResult:
    config = launch.config
    structured_output = launch.structured_output
    limits = config.execution_limits
    result: Any | None = None
    try:
        async with asyncio.timeout(limits.total_timeout_seconds):
            result = await consume_agent_stream(
                agent,
                request,
                recorder,
                UsageLimits(
                    request_limit=limits.request_limit,
                    tool_calls_limit=limits.tool_calls_limit,
                    output_tokens_limit=config.max_output_tokens,
                ),
                early_output_model=(
                    request.output_model
                    if (
                        request.output_model is not None
                        and structured_output is not None
                        and request.allow_early_output
                        and structured_output.mode is StructuredOutputMode.NATIVE
                    )
                    else None
                ),
            )
        if result is None:
            raise RuntimeError("Pydantic AI event stream finished without a run result.")
        recorder.complete(result)
        usage = {
            **agent_usage(result),
            **launch.context_guard.state.usage_metadata(),
            **output_mode_usage_metadata(structured_output, request.model_role),
            "llm_transcript_id": recorder.transcript.id,
            "llm_transcript_status": recorder.transcript.status.value,
            "max_concurrent_agents": config.max_concurrent_agents,
            "request_limit": limits.request_limit,
            "tool_calls_limit": limits.tool_calls_limit,
            "total_timeout_seconds": limits.total_timeout_seconds,
            "max_output_tokens": config.max_output_tokens,
            "early_stream_termination": isinstance(result, BaseModel),
        }
        return PydanticAgentRuntimeResult(
            output=validated_runtime_output(result, request.output_model),
            usage=usage,
            transcript_id=recorder.transcript.id,
            raw_result=result,
        )
    except PydanticAgentRunCancelledError as exc:
        recorder.cancel(str(exc))
        raise
    except TimeoutError as exc:
        timeout_error = actionable_timeout_error(exc, limits.total_timeout_seconds)
        recorder.fail(timeout_error)
        raise timeout_error from exc
    except Exception as exc:
        recorder.fail(exc)
        raise
    finally:
        await close_model_client(launch.model)


def validated_runtime_output(
    result: Any,
    output_model: type[BaseModel] | None,
) -> BaseModel | str:
    raw_output = result if isinstance(result, BaseModel | str) else result.output
    if output_model is None:
        if not isinstance(raw_output, str):
            raise TypeError("Plain-text agent returned a non-text final output.")
        return raw_output
    return output_model.model_validate(raw_output)


def output_mode_usage_metadata(
    selection: StructuredOutputSelection | None,
    role: ModelRole,
) -> dict[str, Any]:
    if selection is not None:
        return selection.usage_metadata(role.value)
    prefix = role.value
    return {
        f"{prefix}_structured_output_mode": "text",
        f"{prefix}_structured_output_schema": None,
        f"{prefix}_structured_output_schema_sha256": None,
        f"{prefix}_structured_output_diagnostics": [],
    }


def actionable_timeout_error(error: TimeoutError, total_seconds: int) -> TimeoutError:
    detail = str(error).strip() or (
        f"Pydantic AI runtime exceeded total deadline of {total_seconds} seconds."
    )
    return TimeoutError(detail)


async def consume_agent_stream[DepsT](
    agent: Agent[DepsT, Any],
    request: PydanticAgentRunRequest[DepsT],
    recorder: LLMTranscriptRecorder,
    usage_limits: UsageLimits,
    *,
    early_output_model: type[BaseModel] | None = None,
) -> Any:
    async def consume() -> Any:
        async with agent.run_stream_events(
            request.prompt,
            deps=request.deps,
            usage_limits=usage_limits,
        ) as stream:
            return await consume_stream_events(
                stream,
                recorder,
                early_output_model=early_output_model,
            )

    stream_task = asyncio.create_task(consume())
    if request.workflow_task_id is None:
        return await stream_task
    cancellation_task = asyncio.create_task(
        wait_for_workflow_cancellation(request.workflow_task_id)
    )
    tasks = (stream_task, cancellation_task)
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if cancellation_task in done:
            raise PydanticAgentRunCancelledError("Model run cancelled at user request.")
        return await stream_task
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def consume_stream_events(
    stream: AsyncIterable[Any],
    recorder: PydanticEventRecorder,
    *,
    early_output_model: type[BaseModel] | None = None,
) -> Any | None:
    text_parts: dict[int, str] = {}
    output_tool = EarlyOutputToolState()
    async for event in stream:
        if isinstance(event, AgentRunResultEvent):
            return event.result
        recorder.record_pydantic_event(event)
        if early_output_model is None:
            continue
        output_payload = updated_early_output_payload(
            text_parts,
            output_tool,
            event,
        )
        if output_payload is None:
            continue
        try:
            output = (
                early_output_model.model_validate_json(output_payload)
                if isinstance(output_payload, str)
                else early_output_model.model_validate(output_payload)
            )
        except ValidationError:
            continue
        return output
    return None


def updated_early_output_payload(
    text_parts: dict[int, str],
    output_tool: EarlyOutputToolState,
    event: Any,
) -> str | dict[str, Any] | None:
    update_output_tool_state(output_tool, event)
    output_text = updated_text_output(text_parts, event)
    if output_text is not None:
        return output_text
    return final_output_tool_payload(output_tool)


def final_output_tool_payload(
    output_tool: EarlyOutputToolState,
) -> str | dict[str, Any] | None:
    if output_tool.tool_name is None:
        return None
    part = matching_output_tool_part(output_tool)
    if part is None:
        return None
    args_as_dict = getattr(part, "args_as_dict", None)
    if callable(args_as_dict):
        try:
            payload = cast(dict[str, Any], args_as_dict(raise_if_invalid=True))
        except (AssertionError, ValueError):
            payload = None
    else:
        args = getattr(part, "args", None)
        payload = args if isinstance(args, dict | str) else None
    return payload


def matching_output_tool_part(
    output_tool: EarlyOutputToolState,
) -> Any | None:
    if output_tool.tool_call_id is not None:
        completed = output_tool.completed_parts.get(output_tool.tool_call_id)
        if completed is not None and completed.tool_name == output_tool.tool_name:
            return completed
    return next(
        (
            part
            for index in sorted(output_tool.streamed_parts, reverse=True)
            if (part := output_tool.streamed_parts[index]).tool_name == output_tool.tool_name
            and (
                output_tool.tool_call_id is None
                or part.tool_call_id == output_tool.tool_call_id
            )
        ),
        None,
    )


def update_output_tool_state(output_tool: EarlyOutputToolState, event: Any) -> None:
    update_tool_call_parts(output_tool.streamed_parts, event)
    event_kind = getattr(event, "event_kind", None)
    if event_kind == "output_tool_call":
        part = getattr(event, "part", None)
        tool_call_id = getattr(part, "tool_call_id", None)
        if getattr(part, "part_kind", None) == "tool-call" and isinstance(
            tool_call_id, str
        ):
            output_tool.completed_parts[tool_call_id] = part
    if event_kind != "final_result":
        return
    tool_name = getattr(event, "tool_name", None)
    if not isinstance(tool_name, str) or not tool_name:
        return
    output_tool.tool_name = tool_name
    tool_call_id = getattr(event, "tool_call_id", None)
    output_tool.tool_call_id = tool_call_id if isinstance(tool_call_id, str) else None


def update_tool_call_parts(tool_call_parts: dict[int, Any], event: Any) -> None:
    event_kind = getattr(event, "event_kind", None)
    index = getattr(event, "index", None)
    if not isinstance(index, int):
        return
    if event_kind in {"part_start", "part_end"}:
        part = getattr(event, "part", None)
        if getattr(part, "part_kind", None) == "tool-call":
            tool_call_parts[index] = part
        return
    if event_kind != "part_delta":
        return
    delta = getattr(event, "delta", None)
    if getattr(delta, "part_delta_kind", None) != "tool_call":
        return
    existing = tool_call_parts.get(index)
    apply_delta = getattr(delta, "apply", None)
    if existing is not None and callable(apply_delta):
        tool_call_parts[index] = apply_delta(existing)
        return
    as_part = getattr(delta, "as_part", None)
    if callable(as_part) and (part := as_part()) is not None:
        tool_call_parts[index] = part


def updated_text_output(text_parts: dict[int, str], event: Any) -> str | None:
    event_kind = getattr(event, "event_kind", None)
    index = getattr(event, "index", None)
    if not isinstance(index, int):
        return None
    if event_kind == "part_start":
        part = getattr(event, "part", None)
        if getattr(part, "part_kind", None) != "text":
            return None
        text_parts[index] = getattr(part, "content", "")
    elif event_kind == "part_delta":
        delta = getattr(event, "delta", None)
        if getattr(delta, "part_delta_kind", None) != "text":
            return None
        text_parts[index] = text_parts.get(index, "") + getattr(delta, "content_delta", "")
    else:
        return None
    return "".join(text_parts[index] for index in sorted(text_parts)).strip()


async def wait_for_workflow_cancellation(task_id: str) -> None:
    store = create_project_workflow_store()
    while True:
        task = await asyncio.to_thread(store.get, task_id)
        if task is not None and task.status is ProjectWorkflowTaskStatus.CANCELLED:
            return
        await asyncio.sleep(2)


def run_pydantic_agent_sync[DepsT](
    request: PydanticAgentRunRequest[DepsT],
) -> PydanticAgentRuntimeResult:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_pydantic_agent(request))
    result: PydanticAgentRuntimeResult | None = None
    error: BaseException | None = None

    def run_in_thread() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(run_pydantic_agent(request))
        except BaseException as exc:  # noqa: BLE001 - re-raised in caller thread
            error = exc

    thread = threading.Thread(
        target=run_in_thread,
        name="guidesync-pydantic-agent",
        daemon=True,
    )
    thread.start()
    total_timeout_seconds = request.config.execution_limits.total_timeout_seconds
    thread.join(timeout=total_timeout_seconds + 1)
    if thread.is_alive():
        raise TimeoutError(
            f"Pydantic AI runtime exceeded total deadline of {total_timeout_seconds} seconds."
        )
    if error is not None:
        raise error
    if result is None:
        raise RuntimeError("Pydantic AI runtime thread exited without a result.")
    return result


async def close_model_client(model: Any) -> None:
    try:
        client = getattr(model, "client", None)
        close = getattr(client, "close", None)
        if not callable(close):
            return
        result = close()
        if isawaitable(result):
            await result
    except Exception:  # noqa: BLE001 - cleanup should not fail a successful model run
        return


def model_settings_from_provider(config: ProviderConfig) -> AgentModelSettings | None:
    config = pydantic_ai_generation_config(config)
    settings: dict[str, Any] = {}
    if config.thinking is not None:
        if config.model.startswith(("openai:", "openai-chat:", "openai-responses:")):
            settings["openai_reasoning_effort"] = openai_reasoning_effort(config.thinking)
        else:
            settings["thinking"] = config.thinking
    if config.max_output_tokens is not None:
        settings["max_tokens"] = config.max_output_tokens
    if config.temperature is not None:
        settings["temperature"] = config.temperature
    return cast(AgentModelSettings, settings) if settings else None


def openai_reasoning_effort(thinking: bool | str) -> str:
    if thinking is True:
        return "medium"
    if thinking is False:
        return "none"
    return thinking


def agent_usage(result: Any) -> dict[str, Any]:
    if not hasattr(result, "usage"):
        return {}
    try:
        usage = result.usage
        usage_dump = getattr(usage, "model_dump", None)
        if callable(usage_dump):
            return usage_dump()
        if is_dataclass(usage):
            return asdict(usage)
        usage_obj = usage() if callable(usage) else usage
        usage_dump = getattr(usage_obj, "model_dump", None)
        return usage_dump() if callable(usage_dump) else {}
    except Exception:  # noqa: BLE001 - best effort metadata only
        return {}


def transcript_prompt_text(prompt: str | Sequence[UserContent]) -> str:
    if isinstance(prompt, str):
        return prompt
    parts: list[str] = []
    for item in prompt:
        kind = getattr(item, "kind", item.__class__.__name__)
        if isinstance(item, str):
            parts.append(item)
            continue
        content = getattr(item, "content", None)
        if isinstance(content, str):
            parts.append(content)
            continue
        data = getattr(item, "data", None)
        media_type = getattr(item, "media_type", None)
        if isinstance(data, bytes):
            parts.append(f"[{kind}:{media_type or 'application/octet-stream'}:{len(data)} bytes]")
            continue
        url = getattr(item, "url", None)
        if isinstance(url, str):
            parts.append(f"[{kind}:{url}]")
            continue
        parts.append(f"[{kind}]")
    return "\n".join(parts)
