from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from guidesync_agent.schemas.agent_harness import (
    AgentContextTrustLevel,
    AgentToolDefinition,
    AgentToolResultStatus,
)

type JsonValue = Any


class AgentLoopToolName(StrEnum):
    INSPECT_REPOSITORY_SUMMARY = "inspect_repository_summary"
    LIST_ALLOWED_DIRECTORIES = "list_allowed_directories"
    LIST_DIRECTORY = "list_directory"
    LIST_DIRECTORY_WITH_SIZES = "list_directory_with_sizes"
    DIRECTORY_TREE = "directory_tree"
    SEARCH_FILES = "search_files"
    READ_TEXT_FILE = "read_text_file"
    READ_MULTIPLE_FILES = "read_multiple_files"
    GET_FILE_INFO = "get_file_info"
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


class AgentLoopObservation(BaseModel):
    id: str = Field(default_factory=lambda: f"obs-{uuid4().hex[:10]}")
    tool_name: AgentLoopToolName
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    result_status: AgentToolResultStatus = AgentToolResultStatus.SUCCESS
    trust_level: AgentContextTrustLevel = AgentContextTrustLevel.UNTRUSTED_PROVIDER
    output_summary: str = ""
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_ref: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
