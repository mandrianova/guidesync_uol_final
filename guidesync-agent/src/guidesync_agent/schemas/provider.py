from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from guidesync_agent.llm.settings import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TIMEOUT_SECONDS,
)

from .common import ProviderKind, ThinkingSetting
from .model_roles import ModelRole


class StructuredOutputMode(StrEnum):
    TOOL = "tool"
    NATIVE = "native"
    PROMPTED = "prompted"


class LocalHTTPChatEndpoint(StrEnum):
    CUSTOM_CHAT = "custom_chat"
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"


class StructuredOutputCapabilities(BaseModel):
    tool_output: bool = True
    native_json_schema: bool = False
    prompted_output: bool = True
    tool_native_compatible: bool = False


class StructuredOutputSelection(BaseModel):
    mode: StructuredOutputMode
    schema_name: str
    schema_sha256: str
    capabilities: StructuredOutputCapabilities = Field(default_factory=StructuredOutputCapabilities)
    diagnostics: list[str] = Field(default_factory=list)

    def usage_metadata(self, prefix: str) -> dict[str, Any]:
        return {
            f"{prefix}_structured_output_mode": self.mode.value,
            f"{prefix}_structured_output_schema": self.schema_name,
            f"{prefix}_structured_output_schema_sha256": self.schema_sha256,
            f"{prefix}_structured_output_diagnostics": self.diagnostics,
        }


class ProviderConfig(BaseModel):
    provider: ProviderKind = ProviderKind.PYDANTIC_AI
    model: str = DEFAULT_LLM_MODEL
    name: str | None = None
    base_url: str | None = DEFAULT_LLM_BASE_URL
    api_key_env: str | None = None
    api_key: str | None = Field(default=None, exclude=True)
    timeout_seconds: int = Field(default=DEFAULT_LLM_TIMEOUT_SECONDS, ge=1)
    thinking: ThinkingSetting | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelSettings(BaseModel):
    id: str = "global-default"
    name: str = "Default model"
    provider: ProviderKind = ProviderKind.PYDANTIC_AI
    model: str = DEFAULT_LLM_MODEL
    base_url: str | None = DEFAULT_LLM_BASE_URL
    api_key: str | None = Field(default=None, exclude=True)
    has_api_key: bool = False
    is_default: bool = True
    timeout_seconds: int = Field(default=DEFAULT_LLM_TIMEOUT_SECONDS, ge=1)
    thinking: ThinkingSetting | None = None
    roles: list[ModelRole] = Field(default_factory=list)


class ModelSettingsUpdate(BaseModel):
    name: str | None = None
    provider: ProviderKind
    model: str
    base_url: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    timeout_seconds: int = Field(default=DEFAULT_LLM_TIMEOUT_SECONDS, ge=1)
    thinking: ThinkingSetting | None = None
    roles: list[ModelRole] | None = None


class RequestedModelSettings(BaseModel):
    model_profile_id: str | None = None
    provider: ProviderKind | None = None
    model: str | None = None
    base_url: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    thinking: ThinkingSetting | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EffectiveModelConfiguration(BaseModel):
    model_profile_id: str | None = None
    name: str | None = None
    provider: ProviderKind
    model: str
    base_url: str | None = None
    timeout_seconds: int = Field(ge=1)
    thinking: ThinkingSetting | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
