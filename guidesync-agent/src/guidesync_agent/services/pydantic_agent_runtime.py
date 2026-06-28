from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from inspect import isawaitable
from typing import Any, TypeVar, cast

from pydantic import BaseModel
from pydantic_ai import Agent, AgentRunResultEvent
from pydantic_ai.settings import ModelSettings as AgentModelSettings

from guidesync_agent.llm.factory import build_pydantic_ai_model
from guidesync_agent.llm.structured_output import (
    pydantic_ai_output_type,
    select_structured_output,
)
from guidesync_agent.schemas import ModelRole, ProviderConfig
from guidesync_agent.services.llm_transcript_recorder import LLMTranscriptRecorder

DepsT = TypeVar("DepsT")
OutputModelT = TypeVar("OutputModelT", bound=BaseModel)
ToolRegistrar = Callable[[Agent[Any, Any]], None]


@dataclass
class PydanticAgentRuntimeResult:
    output: BaseModel
    usage: dict[str, Any]
    transcript_id: str | None
    raw_result: Any


async def run_pydantic_agent(
    *,
    prompt: str,
    instructions: str,
    output_model: type[OutputModelT],
    deps: DepsT,
    deps_type: type[DepsT],
    config: ProviderConfig,
    model_role: ModelRole,
    project_id: str | None = None,
    run_id: str | None = None,
    workflow_task_id: str | None = None,
    model_call_id: str | None = None,
    token_ledger_entry_id: str | None = None,
    prompt_metadata: Mapping[str, Any] | None = None,
    register_tools: ToolRegistrar | None = None,
    retries: int = 3,
    requires_tools: bool = True,
) -> PydanticAgentRuntimeResult:
    model = build_pydantic_ai_model(config)
    structured_output = select_structured_output(
        config,
        output_model,
        requires_tools=requires_tools,
    )
    recorder = LLMTranscriptRecorder(
        project_id=project_id,
        run_id=run_id,
        workflow_task_id=workflow_task_id,
        model_role=model_role,
        provider=config.provider,
        model=config.model,
        metadata={
            **config.metadata,
            "provider": config.provider.value,
            "model": config.model,
            "base_url": config.base_url,
            "timeout_seconds": config.timeout_seconds,
            "thinking": config.thinking,
            "prompt_metadata": dict(prompt_metadata or {}),
        },
        model_call_id=model_call_id,
        token_ledger_entry_id=token_ledger_entry_id,
        endpoint_type=config.metadata.get("endpoint_type")
        if isinstance(config.metadata.get("endpoint_type"), str)
        else None,
    )
    recorder.start(initial_prompt=prompt)
    agent = cast(
        Agent[DepsT, OutputModelT],
        Agent(
            model,
            output_type=pydantic_ai_output_type(output_model, structured_output),
            instructions=instructions,
            deps_type=deps_type,
            model_settings=model_settings_from_provider(config),
            retries=retries,
        ),
    )
    if register_tools is not None:
        register_tools(agent)

    result: Any | None = None
    try:
        async with agent.run_stream_events(prompt, deps=deps) as stream:
            async for event in stream:
                if isinstance(event, AgentRunResultEvent):
                    result = event.result
                    continue
                recorder.record_pydantic_event(event)
        if result is None:
            raise RuntimeError("Pydantic AI event stream finished without a run result.")
        recorder.complete(result)
        usage = {
            **agent_usage(result),
            **structured_output.usage_metadata(model_role.value),
            "llm_transcript_id": recorder.transcript.id,
            "llm_transcript_status": recorder.transcript.status.value,
        }
        return PydanticAgentRuntimeResult(
            output=output_model.model_validate(result.output),
            usage=usage,
            transcript_id=recorder.transcript.id,
            raw_result=result,
        )
    except Exception as exc:
        recorder.fail(exc)
        raise
    finally:
        await close_model_client(model)


def run_pydantic_agent_sync(**kwargs: Any) -> PydanticAgentRuntimeResult:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_pydantic_agent(**kwargs))
    result: PydanticAgentRuntimeResult | None = None
    error: BaseException | None = None

    def run_in_thread() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(run_pydantic_agent(**kwargs))
        except BaseException as exc:  # noqa: BLE001 - re-raised in caller thread
            error = exc

    thread = threading.Thread(target=run_in_thread, name="guidesync-pydantic-agent")
    thread.start()
    thread.join()
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
    settings: dict[str, Any] = {}
    if config.thinking is not None:
        settings["thinking"] = config.thinking
    max_tokens = positive_int_metadata(config, "max_output_tokens", "max_tokens")
    if max_tokens is not None:
        settings["max_tokens"] = max_tokens
    temperature = numeric_metadata(config, "temperature")
    if temperature is not None:
        settings["temperature"] = temperature
    return cast(AgentModelSettings, settings) if settings else None


def positive_int_metadata(config: ProviderConfig, *keys: str) -> int | None:
    for key in keys:
        value = config.metadata.get(key)
        if value in (None, ""):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def numeric_metadata(config: ProviderConfig, key: str) -> float | None:
    value = config.metadata.get(key)
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


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
