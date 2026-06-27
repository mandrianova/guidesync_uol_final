from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, Field

from guidesync_agent.schemas.agent_harness import (
    AgentContextTrustLevel,
    AgentToolDefinition,
    AgentToolResultStatus,
)

JsonValue: TypeAlias = Any


class AgentLoopActionType(StrEnum):
    TOOL_CALL = "tool_call"
    FINAL = "final"


class AgentLoopToolName(StrEnum):
    INSPECT_REPOSITORY_SUMMARY = "inspect_repository_summary"
    LIST_REPOSITORY_FILES = "list_repository_files"
    READ_REPOSITORY_FILE = "read_repository_file"
    SEARCH_REPOSITORY_FILES = "search_repository_files"
    READ_RAW_DIFF = "read_raw_diff"
    READ_PROJECT_PROFILE = "read_project_profile"
    SEARCH_KNOWLEDGE_BASE = "search_knowledge_base"
    READ_KNOWLEDGE_DOCUMENT = "read_knowledge_document"


class AgentLoopToolDescriptor(BaseModel):
    name: AgentLoopToolName
    description: str
    argument_schema: dict[str, JsonValue] = Field(default_factory=dict)
    definition: AgentToolDefinition | None = None


class AgentLoopToolCall(BaseModel):
    tool_name: AgentLoopToolName
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    reason: str = ""


class AgentLoopModelAction(BaseModel):
    action: AgentLoopActionType
    tool_call: AgentLoopToolCall | None = None
    final_output: dict[str, JsonValue] = Field(default_factory=dict)
    reasoning_summary: str = ""


class AgentLoopObservation(BaseModel):
    id: str = Field(default_factory=lambda: f"obs-{uuid4().hex[:10]}")
    tool_name: AgentLoopToolName
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    ok: bool = True
    result_status: AgentToolResultStatus = AgentToolResultStatus.SUCCESS
    trust_level: AgentContextTrustLevel = AgentContextTrustLevel.UNTRUSTED_PROVIDER
    output_summary: str = ""
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_ref: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentLoopCompactionCheckpoint(BaseModel):
    id: str = Field(default_factory=lambda: f"agent-loop-compact-{uuid4().hex[:10]}")
    summarized_observation_ids: list[str] = Field(default_factory=list)
    trigger_token_estimate: int = 0
    retained_observation_count: int = 0
    summary: str = ""
    artifact_ref: str | None = None
    provider: str = "deterministic"
    model: str = "deterministic"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentLoopRequest(BaseModel):
    task_name: str
    task_goal: str
    project_id: str | None = None
    profile_id: str | None = None
    instructions: str = ""
    context: dict[str, JsonValue] = Field(default_factory=dict)
    tool_descriptors: list[AgentLoopToolDescriptor] = Field(default_factory=list)
    tool_registry_id: str = "guidesync-read-only-agent-tools:v1"
    tool_policy_summary: str = (
        "Read-only scoped repository, diff, knowledge, profile, browser, and "
        "validation tools. File writes, process execution, external network calls, "
        "message sending, repository mutation, database mutation, and out-of-scope "
        "reads are denied."
    )
    resource_scopes: list[str] = Field(default_factory=list)


class AgentLoopPromptContext(BaseModel):
    request: AgentLoopRequest
    observations: list[AgentLoopObservation] = Field(default_factory=list)
    compaction_checkpoints: list[AgentLoopCompactionCheckpoint] = Field(default_factory=list)
    token_estimate: int = 0


class AgentLoopResult(BaseModel):
    final_output: dict[str, JsonValue]
    observations: list[AgentLoopObservation] = Field(default_factory=list)
    compaction_checkpoints: list[AgentLoopCompactionCheckpoint] = Field(default_factory=list)
    model_actions: list[AgentLoopModelAction] = Field(default_factory=list)
    provider: str
    model: str
    model_metadata: dict[str, JsonValue] = Field(default_factory=dict)
