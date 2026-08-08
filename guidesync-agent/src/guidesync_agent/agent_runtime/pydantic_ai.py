from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, is_dataclass
from inspect import isawaitable
from typing import Any, Generic, Protocol, TypeVar, cast

from pydantic import BaseModel
from pydantic_ai import Agent, AgentRunResultEvent, UsageLimits
from pydantic_ai.messages import UserContent
from pydantic_ai.settings import ModelSettings as AgentModelSettings

from guidesync_agent.agent_runtime.concurrency import agent_concurrency_limiter
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
from guidesync_agent.schemas import ModelRole, ProjectWorkflowTaskStatus, ProviderConfig
from guidesync_agent.storage import create_project_workflow_store

DepsT = TypeVar("DepsT")
OutputModelT = TypeVar("OutputModelT", bound=BaseModel)
ToolRegistrar = Callable[[Agent[Any, Any]], None]


class PydanticEventRecorder(Protocol):
    def record_pydantic_event(self, event: Any) -> None: ...


class PydanticAgentRunCancelledError(RuntimeError):
    pass


@dataclass
class PydanticAgentRuntimeResult:
    output: BaseModel
    usage: dict[str, Any]
    transcript_id: str | None
    raw_result: Any


@dataclass(frozen=True)
class PydanticAgentRunRequest(Generic[DepsT, OutputModelT]):
    prompt: str | Sequence[UserContent]
    instructions: str
    output_model: type[OutputModelT]
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


async def run_pydantic_agent(
    request: PydanticAgentRunRequest[DepsT, OutputModelT],
) -> PydanticAgentRuntimeResult:
    config = pydantic_ai_generation_config(request.config)
    async with agent_concurrency_limiter.slot(config):
        model = build_pydantic_ai_model(config)
        structured_output = select_structured_output(
            config,
            request.output_model,
            requires_tools=request.requires_tools,
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
        agent = cast(
            Agent[DepsT, OutputModelT],
            Agent(
                model,
                output_type=pydantic_ai_output_type(request.output_model, structured_output),
                instructions=request.instructions,
                deps_type=request.deps_type,
                model_settings=model_settings_from_provider(config),
                retries=request.retries if request.retries is not None else limits.retries,
            ),
        )
        if request.register_tools is not None:
            request.register_tools(agent)

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
                )
            if result is None:
                raise RuntimeError("Pydantic AI event stream finished without a run result.")
            recorder.complete(result)
            usage = {
                **agent_usage(result),
                **structured_output.usage_metadata(request.model_role.value),
                "llm_transcript_id": recorder.transcript.id,
                "llm_transcript_status": recorder.transcript.status.value,
                "max_concurrent_agents": config.max_concurrent_agents,
                "request_limit": limits.request_limit,
                "tool_calls_limit": limits.tool_calls_limit,
                "total_timeout_seconds": limits.total_timeout_seconds,
                "max_output_tokens": config.max_output_tokens,
            }
            return PydanticAgentRuntimeResult(
                output=request.output_model.model_validate(result.output),
                usage=usage,
                transcript_id=recorder.transcript.id,
                raw_result=result,
            )
        except PydanticAgentRunCancelledError as exc:
            recorder.cancel(str(exc))
            raise
        except Exception as exc:
            recorder.fail(exc)
            raise
        finally:
            await close_model_client(model)


async def consume_agent_stream(
    agent: Agent[DepsT, OutputModelT],
    request: PydanticAgentRunRequest[DepsT, OutputModelT],
    recorder: LLMTranscriptRecorder,
    usage_limits: UsageLimits,
) -> Any:
    async def consume() -> Any:
        async with agent.run_stream_events(
            request.prompt,
            deps=request.deps,
            usage_limits=usage_limits,
        ) as stream:
            return await consume_stream_events(stream, recorder)

    stream_task = asyncio.create_task(consume())
    if request.workflow_task_id is None:
        return await stream_task
    cancellation_task = asyncio.create_task(
        wait_for_workflow_cancellation(request.workflow_task_id)
    )
    done, _ = await asyncio.wait(
        {stream_task, cancellation_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if cancellation_task in done:
        stream_task.cancel()
        with suppress(asyncio.CancelledError):
            await stream_task
        raise PydanticAgentRunCancelledError("Model run cancelled at user request.")
    cancellation_task.cancel()
    with suppress(asyncio.CancelledError):
        await cancellation_task
    return await stream_task


async def consume_stream_events(
    stream: AsyncIterable[Any],
    recorder: PydanticEventRecorder,
) -> Any | None:
    async for event in stream:
        if isinstance(event, AgentRunResultEvent):
            return event.result
        recorder.record_pydantic_event(event)
    return None


async def wait_for_workflow_cancellation(task_id: str) -> None:
    store = create_project_workflow_store()
    while True:
        task = await asyncio.to_thread(store.get, task_id)
        if task is not None and task.status is ProjectWorkflowTaskStatus.CANCELLED:
            return
        await asyncio.sleep(2)


def run_pydantic_agent_sync(
    request: PydanticAgentRunRequest[DepsT, OutputModelT],
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
