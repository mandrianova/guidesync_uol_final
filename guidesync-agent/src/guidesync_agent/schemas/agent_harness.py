from __future__ import annotations

from enum import StrEnum
from typing import Any, TypeAlias

from pydantic import BaseModel, Field

JsonValue: TypeAlias = Any


class AgentToolRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AgentToolSideEffect(StrEnum):
    READ_ONLY = "read_only"
    WRITE = "write"
    MUTATION = "mutation"
    EXTERNAL_NETWORK = "external_network"
    PROCESS_EXECUTION = "process_execution"


class AgentToolScope(StrEnum):
    REPOSITORY_CACHE = "repository_cache"
    RAW_DIFF = "raw_diff"
    PROJECT_PROFILE = "project_profile"
    KNOWLEDGE_BASE = "knowledge_base"
    BROWSER_READ = "browser_read"
    VALIDATION = "validation"


class AgentToolPermission(StrEnum):
    READ_ONLY_ALLOWED = "read_only_allowed"
    DENIED = "denied"


class AgentToolResultStatus(StrEnum):
    SUCCESS = "success"
    TOOL_ERROR = "tool_error"
    INVALID_ARGUMENTS = "invalid_arguments"
    DENIED = "denied"
    TIMEOUT = "timeout"
    UNSUPPORTED_TOOL = "unsupported_tool"
    TRUNCATED = "truncated"


class AgentContextTrustLevel(StrEnum):
    CONTROL = "control"
    UNTRUSTED_REPOSITORY = "untrusted_repository"
    UNTRUSTED_DIFF = "untrusted_diff"
    UNTRUSTED_KNOWLEDGE = "untrusted_knowledge"
    UNTRUSTED_BROWSER = "untrusted_browser"
    UNTRUSTED_PROVIDER = "untrusted_provider"
    TOOL_STATUS = "tool_status"


class AgentToolDefinition(BaseModel):
    name: str
    purpose: str
    input_schema: dict[str, JsonValue] = Field(default_factory=dict)
    output_schema: dict[str, JsonValue] = Field(default_factory=dict)
    risk: AgentToolRisk = AgentToolRisk.LOW
    side_effect: AgentToolSideEffect = AgentToolSideEffect.READ_ONLY
    scope: AgentToolScope
    permission: AgentToolPermission = AgentToolPermission.READ_ONLY_ALLOWED
    timeout_seconds: float = Field(default=10.0, gt=0)
    max_output_chars: int = Field(default=32_000, ge=1)
    retry_policy: str = "no automatic retry"
    audit_summary: str = ""


class AgentToolResult(BaseModel):
    status: AgentToolResultStatus
    tool_name: str
    output_summary: str = ""
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_ref: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    trust_level: AgentContextTrustLevel = AgentContextTrustLevel.TOOL_STATUS
