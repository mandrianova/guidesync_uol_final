from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any

from guidesync_agent.agent_runtime.transcript_payloads import (
    conversation_id_for,
    endpoint_metadata,
    model_settings,
    sanitize_secret_value,
)
from guidesync_agent.agent_runtime.transcript_types import (
    LLMTranscriptContext,
    LLMTranscriptEventData,
)
from guidesync_agent.schemas import (
    LLMConversationStatus,
    LLMConversationTranscript,
    LLMMessageRole,
    LLMMessageSource,
    LLMRedactionStatus,
    LLMTranscriptEvent,
    LLMTranscriptEventKind,
)
from guidesync_agent.storage import create_llm_transcript_store


class LLMTranscriptRecorder:
    def __init__(self, context: LLMTranscriptContext) -> None:
        self.project_id = context.project_id
        self.run_id = context.run_id
        self.workflow_task_id = context.workflow_task_id
        self.model_role = context.model_role
        self.provider = context.provider
        self.model = context.model
        self.metadata = dict(context.metadata)
        self.started_at = context.started_at
        self.model_call_id = context.model_call_id
        self.token_ledger_entry_id = context.token_ledger_entry_id
        self.endpoint_type = context.endpoint_type
        self.store = create_llm_transcript_store()
        self.transcript = self._build_transcript(LLMConversationStatus.PARTIAL)
        self.events: list[LLMTranscriptEvent] = []
        self._started = False

    def start(self, *, initial_prompt: str | None = None) -> LLMConversationTranscript:
        self._started = True
        self.store.save(self.transcript)
        if initial_prompt is not None:
            self.record_event(
                LLMTranscriptEventData(
                    event_kind=LLMTranscriptEventKind.MODEL_REQUEST,
                    role=LLMMessageRole.USER,
                    source=LLMMessageSource.PYDANTIC_AI,
                    content=initial_prompt,
                    metadata={"phase": "initial_prompt"},
                )
            )
        return self.transcript

    def record_event(self, data: LLMTranscriptEventData) -> LLMTranscriptEvent:
        if not self._started:
            self.start()
        event = LLMTranscriptEvent(
            conversation_id=self.transcript.id,
            sequence=len(self.events),
            event_kind=data.event_kind,
            role=data.role,
            source=data.source,
            name=data.name,
            content=stringify_sanitized(data.content),
            tool_call_id=data.tool_call_id,
            tool_name=data.tool_name,
            arguments=dict_sanitized(data.arguments),
            result_payload=dict_sanitized(data.result_payload),
            result_status=data.result_status,
            evidence_refs=data.evidence_refs,
            artifact_refs=data.artifact_refs,
            usage=dict_sanitized(data.usage),
            metadata=dict_sanitized(data.metadata),
            error_message=data.error_message,
        )
        self.events.append(event)
        self.store.save_event(event)
        self._refresh_transcript(LLMConversationStatus.PARTIAL)
        return event

    def record_pydantic_event(self, event: Any) -> None:
        event_kind = getattr(event, "event_kind", event.__class__.__name__)
        if event_kind == "function_tool_call":
            part = getattr(event, "part", None)
            self.record_event(
                LLMTranscriptEventData(
                    event_kind=LLMTranscriptEventKind.TOOL_CALL,
                    role=LLMMessageRole.ASSISTANT,
                    tool_call_id=string_attr(event, "tool_call_id"),
                    tool_name=string_attr(part, "tool_name"),
                    arguments=tool_args(part),
                    content=safe_dump(part),
                    metadata={"pydantic_ai_event_kind": event_kind},
                )
            )
            return
        if event_kind == "function_tool_result":
            part = getattr(event, "part", None)
            self.record_event(
                LLMTranscriptEventData(
                    event_kind=LLMTranscriptEventKind.TOOL_RESULT,
                    role=LLMMessageRole.TOOL,
                    tool_call_id=string_attr(event, "tool_call_id"),
                    tool_name=string_attr(part, "tool_name"),
                    result_payload=tool_result_payload(part),
                    result_status=string_attr(part, "outcome") or "success",
                    content=safe_dump(part),
                    metadata={"pydantic_ai_event_kind": event_kind},
                )
            )
            return
        if event_kind == "output_tool_call":
            part = getattr(event, "part", None)
            self.record_event(
                LLMTranscriptEventData(
                    event_kind=LLMTranscriptEventKind.TOOL_CALL,
                    role=LLMMessageRole.ASSISTANT,
                    tool_call_id=string_attr(event, "tool_call_id"),
                    tool_name=string_attr(part, "tool_name"),
                    arguments=tool_args(part),
                    content=safe_dump(part),
                    metadata={"pydantic_ai_event_kind": event_kind, "output_tool": True},
                )
            )
            return
        if event_kind == "output_tool_result":
            part = getattr(event, "part", None)
            self.record_event(
                LLMTranscriptEventData(
                    event_kind=LLMTranscriptEventKind.TOOL_RESULT,
                    role=LLMMessageRole.TOOL,
                    tool_call_id=string_attr(event, "tool_call_id"),
                    tool_name=string_attr(part, "tool_name"),
                    result_payload=tool_result_payload(part),
                    result_status=string_attr(part, "outcome") or "success",
                    content=safe_dump(part),
                    metadata={"pydantic_ai_event_kind": event_kind, "output_tool": True},
                )
            )
            return
        if event_kind == "part_end":
            part = getattr(event, "part", None)
            part_kind = string_attr(part, "part_kind")
            if part_kind == "text":
                self.record_event(
                    LLMTranscriptEventData(
                        event_kind=LLMTranscriptEventKind.MODEL_RESPONSE,
                        role=LLMMessageRole.ASSISTANT,
                        content=getattr(part, "content", ""),
                        metadata={
                            "pydantic_ai_event_kind": event_kind,
                            "part_kind": part_kind,
                        },
                    )
                )
            elif part_kind == "thinking":
                self.record_event(
                    LLMTranscriptEventData(
                        event_kind=LLMTranscriptEventKind.MODEL_RESPONSE,
                        role=LLMMessageRole.PROVIDER,
                        content="[REDACTED_MODEL_REASONING]",
                        metadata={
                            "pydantic_ai_event_kind": event_kind,
                            "part_kind": part_kind,
                        },
                    )
                )
            return
        if event_kind == "final_result":
            self.record_event(
                LLMTranscriptEventData(
                    event_kind=LLMTranscriptEventKind.FINAL_SNAPSHOT,
                    role=LLMMessageRole.PROVIDER,
                    content=safe_dump(event),
                    metadata={"pydantic_ai_event_kind": event_kind},
                )
            )

    def complete(
        self,
        result: Any,
        *,
        completed_at: datetime | None = None,
    ) -> LLMConversationTranscript:
        completed_at = completed_at or datetime.now(UTC)
        self.record_event(
            LLMTranscriptEventData(
                event_kind=LLMTranscriptEventKind.FINAL_SNAPSHOT,
                role=LLMMessageRole.PROVIDER,
                content=result_messages_json(result),
                usage=result_usage(result),
                metadata={"snapshot": "all_messages_json"},
            )
        )
        return self._refresh_transcript(LLMConversationStatus.COMPLETED, completed_at=completed_at)

    def fail(
        self,
        error: BaseException,
        *,
        completed_at: datetime | None = None,
    ) -> LLMConversationTranscript:
        completed_at = completed_at or datetime.now(UTC)
        self.record_event(
            LLMTranscriptEventData(
                event_kind=LLMTranscriptEventKind.ERROR,
                role=LLMMessageRole.PROVIDER,
                content=str(error),
                error_message=str(error),
            )
        )
        return self._refresh_transcript(
            LLMConversationStatus.FAILED,
            completed_at=completed_at,
            diagnostics={"error": str(error)},
        )

    def _build_transcript(
        self,
        status: LLMConversationStatus,
        *,
        completed_at: datetime | None = None,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> LLMConversationTranscript:
        now = datetime.now(UTC)
        transcript = getattr(self, "transcript", None)
        transcript_id = transcript.id if transcript is not None else None
        values: dict[str, Any] = {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "workflow_task_id": self.workflow_task_id,
            "model_call_id": self.model_call_id,
            "model_role": self.model_role,
            "provider": self.provider,
            "model": self.model,
            "endpoint_type": self.endpoint_type,
            "conversation_id": conversation_id_for(
                self.run_id,
                self.workflow_task_id,
                self.model_role,
            ),
            "status": status,
            "started_at": self.started_at,
            "completed_at": completed_at,
            "created_at": transcript.created_at if transcript is not None else now,
            "updated_at": now,
            "message_count": sum(
                1
                for event in self.events
                if event.event_kind
                in {
                    LLMTranscriptEventKind.MESSAGE,
                    LLMTranscriptEventKind.MODEL_REQUEST,
                    LLMTranscriptEventKind.MODEL_RESPONSE,
                    LLMTranscriptEventKind.FINAL_SNAPSHOT,
                    LLMTranscriptEventKind.ERROR,
                }
            )
            if hasattr(self, "events")
            else 0,
            "tool_call_count": sum(
                1
                for event in self.events
                if event.event_kind is LLMTranscriptEventKind.TOOL_CALL
            )
            if hasattr(self, "events")
            else 0,
            "token_ledger_entry_id": self.token_ledger_entry_id,
            "redaction_status": LLMRedactionStatus.REDACTED,
            "prompt_metadata": dict_sanitized(self.metadata.get("prompt_metadata")),
            "provider_metadata": dict_sanitized(self.metadata.get("provider_metadata")),
            "endpoint_metadata": endpoint_metadata(self.metadata),
            "model_settings": model_settings(self.metadata),
            "message_stats": message_stats_from_events(getattr(self, "events", [])),
            "tool_summary": tool_summary_from_events(getattr(self, "events", [])),
            "redaction_metadata": {"policy_version": "llm-transcript-redaction-v1"},
            "diagnostics": {
                **dict_sanitized(diagnostics),
                **dict_sanitized(self.metadata.get("diagnostics")),
            },
            "events": getattr(self, "events", []),
        }
        if transcript_id is not None:
            values["id"] = transcript_id
        return LLMConversationTranscript(**values)

    def _refresh_transcript(
        self,
        status: LLMConversationStatus,
        *,
        completed_at: datetime | None = None,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> LLMConversationTranscript:
        self.transcript = self._build_transcript(
            status,
            completed_at=completed_at,
            diagnostics=diagnostics,
        )
        return self.store.save(self.transcript)


def dict_sanitized(value: Any) -> dict[str, Any]:
    sanitized = sanitize_secret_value(value or {})
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}


def stringify_sanitized(value: Any) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        return json.dumps(sanitize_secret_value(parsed), ensure_ascii=False, default=str)
    sanitized = sanitize_secret_value(value)
    if isinstance(sanitized, str):
        return sanitized
    return json.dumps(sanitized, ensure_ascii=False, default=str)


def safe_dump(value: Any) -> Any:
    if value is None:
        return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return str(value)


def string_attr(value: Any, name: str) -> str | None:
    item = getattr(value, name, None)
    return item if isinstance(item, str) and item else None


def tool_args(part: Any) -> dict[str, Any]:
    args = getattr(part, "args", None)
    if isinstance(args, Mapping):
        return dict_sanitized(args)
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return {"raw": args}
        return dict_sanitized(parsed)
    return {}


def tool_result_payload(part: Any) -> dict[str, Any]:
    content = getattr(part, "content", None)
    if isinstance(content, Mapping):
        return dict_sanitized(content)
    return {"content": stringify_sanitized(content)}


def result_messages_json(result: Any) -> str:
    for method_name in ("all_messages_json", "new_messages_json"):
        method = getattr(result, method_name, None)
        if not callable(method):
            continue
        try:
            raw = method()
        except Exception:  # noqa: BLE001 - final transcript snapshot is best effort
            continue
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return str(raw)
    return safe_dump(result) or ""


def result_usage(result: Any) -> dict[str, Any]:
    usage = getattr(result, "usage", None)
    try:
        model_dump = getattr(usage, "model_dump", None)
        if callable(model_dump):
            return dict_sanitized(model_dump())
    except Exception:  # noqa: BLE001 - usage metadata is best effort
        return {}
    return {}


def message_stats_from_events(events: list[LLMTranscriptEvent]) -> dict[str, Any]:
    messages = [
        event
        for event in events
        if event.event_kind
        in {
            LLMTranscriptEventKind.MESSAGE,
            LLMTranscriptEventKind.MODEL_REQUEST,
            LLMTranscriptEventKind.MODEL_RESPONSE,
            LLMTranscriptEventKind.FINAL_SNAPSHOT,
            LLMTranscriptEventKind.ERROR,
        }
    ]
    counts: dict[str, int] = {}
    for event in messages:
        key = event.role.value if event.role else "provider"
        counts[key] = counts.get(key, 0) + 1
    return {
        "by_role": dict(sorted(counts.items())),
        "content_chars": sum(len(event.content) for event in messages),
    }


def tool_summary_from_events(events: list[LLMTranscriptEvent]) -> dict[str, Any]:
    return {
        "tool_call_count": sum(
            1 for event in events if event.event_kind is LLMTranscriptEventKind.TOOL_CALL
        ),
        "tool_result_count": sum(
            1 for event in events if event.event_kind is LLMTranscriptEventKind.TOOL_RESULT
        ),
        "tools": sorted(
            {
                event.tool_name
                for event in events
                if event.tool_name and event.event_kind is LLMTranscriptEventKind.TOOL_CALL
            }
        ),
    }
