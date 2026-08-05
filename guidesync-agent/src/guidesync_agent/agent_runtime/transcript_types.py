from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from guidesync_agent.schemas import (
    LLMMessageRole,
    LLMMessageSource,
    LLMTranscriptEventKind,
    ModelRole,
    ProviderKind,
)


@dataclass(frozen=True)
class LLMTranscriptContext:
    model_role: ModelRole
    provider: ProviderKind
    model: str
    project_id: str | None = None
    run_id: str | None = None
    workflow_task_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    model_call_id: str | None = None
    token_ledger_entry_id: str | None = None
    endpoint_type: str | None = None


@dataclass(frozen=True)
class LLMTranscriptEventData:
    event_kind: LLMTranscriptEventKind
    role: LLMMessageRole | None = None
    source: LLMMessageSource = LLMMessageSource.PYDANTIC_AI
    name: str | None = None
    content: Any = ""
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments: Mapping[str, Any] | None = None
    result_payload: Mapping[str, Any] | None = None
    result_status: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    usage: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class LocalHttpTranscriptData:
    system_prompt: str
    user_prompt: str
    request_payload: Mapping[str, Any]
    response_payload: Mapping[str, Any]
    output_text: str = ""
    prompt_metadata: Mapping[str, Any] = field(default_factory=dict)
