from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, cast

from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.settings import ModelSettings as AgentModelSettings
from pydantic_ai.tools import ToolDefinition

from guidesync_agent.prompts.loader import load_prompt_file

DEFAULT_CONTEXT_BUDGET_TOKENS = 80_000
DEFAULT_TOOL_RESULT_CHAR_LIMIT = 16_000
MAX_RETAINED_USER_TOKENS = 20_000
SUMMARY_OUTPUT_TOKENS = 2_048
STRUCTURED_CHARS_PER_TOKEN = 3
CONTEXT_SUMMARY_PREFIX = "[GuideSync context checkpoint]"
CONTEXT_SUMMARY_PROMPT_PATH = "shared/context_summary.md"
CONTEXT_SUMMARY_PROMPT_VERSION = "context-summary-v1"

SummaryBuilder = Callable[
    [list[ModelMessage], ModelRequestContext],
    Awaitable[tuple[str, dict[str, int]]],
]


@dataclass
class RuntimeContextState:
    context_budget_tokens: int
    tool_result_char_limit: int
    compaction_count: int = 0
    compacted_message_count: int = 0
    tool_result_truncation_count: int = 0
    last_estimated_prompt_tokens: int = 0
    last_observed_prompt_tokens: int | None = None
    context_compaction_input_tokens: int = 0
    context_compaction_output_tokens: int = 0

    def usage_metadata(self) -> dict[str, int | None]:
        return {
            "context_budget_tokens": self.context_budget_tokens,
            "context_compaction_count": self.compaction_count,
            "context_compacted_message_count": self.compacted_message_count,
            "context_last_estimated_prompt_tokens": self.last_estimated_prompt_tokens,
            "context_last_observed_prompt_tokens": self.last_observed_prompt_tokens,
            "context_compaction_input_tokens": self.context_compaction_input_tokens,
            "context_compaction_output_tokens": self.context_compaction_output_tokens,
            "tool_result_char_limit": self.tool_result_char_limit,
            "tool_result_truncation_count": self.tool_result_truncation_count,
        }


class PydanticAIContextGuard:
    def __init__(
        self,
        *,
        context_budget_tokens: int,
        tool_result_char_limit: int,
        summary_builder: SummaryBuilder | None = None,
    ) -> None:
        self.state = RuntimeContextState(
            context_budget_tokens=max(1, context_budget_tokens),
            tool_result_char_limit=max(1, tool_result_char_limit),
        )
        self._summary_builder = summary_builder or summarize_with_active_model

    def capability(self) -> Hooks[Any]:
        return Hooks(
            before_model_request=self.before_model_request,
            after_model_request=self.after_model_request,
            after_tool_execute=self.after_tool_execute,
        )

    async def before_model_request(
        self,
        ctx: RunContext[Any],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        del ctx
        estimate = estimate_model_request_tokens(request_context)
        self.state.last_estimated_prompt_tokens = estimate
        trigger_tokens = max(
            estimate,
            self.state.last_observed_prompt_tokens or 0,
        )
        if trigger_tokens < self.state.context_budget_tokens:
            return request_context
        if len(request_context.messages) <= 1:
            return request_context

        original_messages = list(request_context.messages)
        summary, usage = await self._summary_builder(
            original_messages,
            request_context,
        )
        summary = summary.strip() or deterministic_message_summary(original_messages)
        request_context.messages = rehydrated_message_history(
            original_messages,
            summary,
            context_budget_tokens=self.state.context_budget_tokens,
        )
        self.state.compaction_count += 1
        self.state.compacted_message_count += len(original_messages)
        self.state.context_compaction_input_tokens += usage.get("input_tokens", 0)
        self.state.context_compaction_output_tokens += usage.get("output_tokens", 0)
        return request_context

    async def after_model_request(
        self,
        ctx: RunContext[Any],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        del ctx, request_context
        self.state.last_observed_prompt_tokens = response.usage.input_tokens
        return response

    async def after_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        result: Any,
    ) -> Any:
        del ctx, tool_def, args
        bounded, truncated = bounded_tool_result(
            result,
            tool_name=call.tool_name,
            char_limit=self.state.tool_result_char_limit,
        )
        if truncated:
            self.state.tool_result_truncation_count += 1
        return bounded


async def summarize_with_active_model(
    messages: list[ModelMessage],
    request_context: ModelRequestContext,
) -> tuple[str, dict[str, int]]:
    prompt = load_prompt_file(
        CONTEXT_SUMMARY_PROMPT_PATH,
        version=CONTEXT_SUMMARY_PROMPT_VERSION,
    )
    settings = dict(request_context.model_settings or {})
    configured_max_tokens = settings.get("max_tokens")
    settings["max_tokens"] = (
        min(configured_max_tokens, SUMMARY_OUTPUT_TOKENS)
        if isinstance(configured_max_tokens, int)
        else SUMMARY_OUTPUT_TOKENS
    )
    settings["temperature"] = 0
    summarizer = Agent(
        request_context.model,
        instructions=prompt.content,
        model_settings=cast(AgentModelSettings, settings),
        retries=1,
    )
    try:
        result = await summarizer.run(
            "Create the context checkpoint now. Do not call tools.",
            message_history=messages,
            usage_limits=UsageLimits(
                request_limit=2,
                output_tokens_limit=SUMMARY_OUTPUT_TOKENS,
            ),
        )
    except Exception:  # noqa: BLE001 - deterministic fallback keeps the main loop alive
        return deterministic_message_summary(messages), {}
    usage = request_usage(result.usage())
    return str(result.output).strip(), usage


def rehydrated_message_history(
    messages: list[ModelMessage],
    summary: str,
    *,
    context_budget_tokens: int,
) -> list[ModelMessage]:
    latest_request = next(
        (message for message in reversed(messages) if isinstance(message, ModelRequest)),
        None,
    )
    retained_user_parts = retained_user_prompt_parts(
        messages,
        token_budget=min(
            MAX_RETAINED_USER_TOKENS,
            max(1, context_budget_tokens // 4),
        ),
    )
    summary_part = UserPromptPart(f"{CONTEXT_SUMMARY_PREFIX}\n\n{summary.strip()}")
    return [
        ModelRequest(
            parts=[*retained_user_parts, summary_part],
            timestamp=latest_request.timestamp if latest_request else None,
            instructions=latest_request.instructions if latest_request else None,
            run_id=latest_request.run_id if latest_request else None,
            conversation_id=latest_request.conversation_id if latest_request else None,
            metadata={"guidesync_context_compaction": True},
        )
    ]


def retained_user_prompt_parts(
    messages: Sequence[ModelMessage],
    *,
    token_budget: int,
) -> list[UserPromptPart]:
    retained: list[UserPromptPart] = []
    remaining_characters = token_budget * STRUCTURED_CHARS_PER_TOKEN
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        for part in reversed(message.parts):
            if not isinstance(part, UserPromptPart) or not isinstance(part.content, str):
                continue
            text = part.content.strip()
            if not text or text.startswith(CONTEXT_SUMMARY_PREFIX):
                continue
            retained_text = truncate_text_middle(text, remaining_characters)
            if not retained_text:
                return list(reversed(retained))
            retained.append(
                UserPromptPart(retained_text, timestamp=part.timestamp)
            )
            remaining_characters -= len(retained_text)
            if remaining_characters <= 0 or retained_text != text:
                return list(reversed(retained))
    return list(reversed(retained))


def estimate_model_request_tokens(request_context: ModelRequestContext) -> int:
    payload = {
        "messages": [json_safe(message) for message in request_context.messages],
        "model_settings": json_safe(request_context.model_settings),
        "model_request_parameters": json_safe(
            request_context.model_request_parameters
        ),
    }
    characters = len(json.dumps(payload, ensure_ascii=False, default=str))
    return max(1, (characters + STRUCTURED_CHARS_PER_TOKEN - 1) // STRUCTURED_CHARS_PER_TOKEN)


def deterministic_message_summary(messages: Sequence[ModelMessage]) -> str:
    lines = ["# Runtime context checkpoint"]
    for message in messages:
        role = "model" if isinstance(message, ModelResponse) else "user/tool"
        for part in message.parts:
            kind = getattr(part, "part_kind", part.__class__.__name__)
            value = part_summary_text(part)
            if value:
                lines.append(f"- {role} {kind}: {value[:500]}")
    return "\n".join(lines)


def part_summary_text(part: Any) -> str:
    content = getattr(part, "content", None)
    if isinstance(content, str):
        return " ".join(content.split())
    if content is not None:
        return compact_json(content)
    tool_name = getattr(part, "tool_name", None)
    args = getattr(part, "args", None)
    if isinstance(tool_name, str):
        return f"{tool_name} args={compact_json(args)}"
    return ""


def bounded_tool_result(
    result: Any,
    *,
    tool_name: str,
    char_limit: int,
) -> tuple[Any, bool]:
    serialized = result if isinstance(result, str) else compact_json(result)
    if len(serialized) <= char_limit:
        return result, False
    marker = (
        f"\n\n[GuideSync tool result truncated: tool={tool_name}; "
        f"original_chars={len(serialized)}. Repeat the tool with a narrower query "
        "or smaller offset/limit to read the omitted section.]"
    )
    if char_limit <= len(marker):
        return marker[:char_limit], True
    preview_limit = max(0, char_limit - len(marker))
    preview = truncate_text_middle(serialized, preview_limit)
    return f"{preview}{marker}", True


def truncate_text_middle(text: str, char_limit: int) -> str:
    if char_limit <= 0:
        return ""
    if len(text) <= char_limit:
        return text
    marker = "\n...[content compacted]...\n"
    if char_limit <= len(marker):
        return marker[:char_limit]
    content_budget = char_limit - len(marker)
    left = content_budget // 2
    right = content_budget - left
    return f"{text[:left]}{marker}{text[-right:]}"


def compact_json(value: Any) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False, default=str, separators=(",", ":"))


def json_safe(value: Any) -> Any:  # noqa: PLR0911 - JSON boundary normalization
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if is_dataclass(value):
        return {key: json_safe(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return json_safe(model_dump(mode="json", exclude_none=True))
    return str(value)


def request_usage(usage: Any) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
    }
