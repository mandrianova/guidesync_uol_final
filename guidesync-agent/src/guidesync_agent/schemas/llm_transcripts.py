from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, Field

from guidesync_agent.schemas.common import ProviderKind
from guidesync_agent.schemas.model_roles import ModelRole

JsonValue: TypeAlias = Any


class LLMConversationStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class LLMMessageRole(StrEnum):
    SYSTEM = "system"
    DEVELOPER = "developer"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    PROVIDER = "provider"


class LLMMessageSource(StrEnum):
    PYDANTIC_AI = "pydantic_ai"
    LOCAL_HTTP = "local_http"
    NORMALIZED = "normalized"


class LLMRedactionStatus(StrEnum):
    REDACTED = "redacted"
    NOT_NEEDED = "not_needed"


class LLMTranscriptMessage(BaseModel):
    role: LLMMessageRole
    source: LLMMessageSource
    content: str = ""
    name: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class LLMToolCallLink(BaseModel):
    name: str
    arguments_summary: dict[str, JsonValue] = Field(default_factory=dict)
    result_status: str = "unknown"
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)


class LLMConversationTranscript(BaseModel):
    id: str = Field(default_factory=lambda: f"llm-conv-{uuid4().hex[:12]}")
    project_id: str | None = None
    run_id: str | None = None
    workflow_task_id: str | None = None
    parent_conversation_id: str | None = None
    model_call_id: str | None = None
    model_role: ModelRole
    provider: ProviderKind
    model: str
    endpoint_type: str | None = None
    conversation_id: str
    turn_index: int = Field(default=0, ge=0)
    status: LLMConversationStatus = LLMConversationStatus.COMPLETED
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    message_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    token_ledger_entry_id: str | None = None
    transcript_artifact_ref: str | None = None
    full_history_artifact_ref: str | None = None
    redaction_status: LLMRedactionStatus = LLMRedactionStatus.REDACTED
    prompt_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    provider_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    endpoint_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    model_settings: dict[str, JsonValue] = Field(default_factory=dict)
    message_stats: dict[str, JsonValue] = Field(default_factory=dict)
    tool_summary: dict[str, JsonValue] = Field(default_factory=dict)
    redaction_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    diagnostics: dict[str, JsonValue] = Field(default_factory=dict)
    messages: list[LLMTranscriptMessage] = Field(default_factory=list)
    tool_calls: list[LLMToolCallLink] = Field(default_factory=list)


class LLMTranscriptSummary(BaseModel):
    id: str
    project_id: str | None = None
    run_id: str | None = None
    workflow_task_id: str | None = None
    model_call_id: str | None = None
    model_role: ModelRole
    provider: ProviderKind
    model: str
    status: LLMConversationStatus
    started_at: datetime
    completed_at: datetime | None = None
    message_count: int = 0
    tool_call_count: int = 0
    transcript_artifact_ref: str | None = None
