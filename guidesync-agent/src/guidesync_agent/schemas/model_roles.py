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


class ModelRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    PROJECT_PROFILE_FILE_READER = "project_profile_file_reader"
    CODE_CHANGE_ANALYSIS = "code_change_analysis"
    SCREENSHOT_VISION = "screenshot_vision"


class ModelProviderFamily(StrEnum):
    GOOGLE = "google"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OPEN_SOURCE = "open_source"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ModelProviderBundle(StrEnum):
    GOOGLE_ALL_IN_ONE = "google_all_in_one"
    ANTHROPIC_QUALITY = "anthropic_quality"
    OPENAI_IMPLEMENTATION_SPEED = "openai_implementation_speed"
    LOCAL_OPEN_SOURCE = "local_open_source"
    MIXED_BEST_FIT = "mixed_best_fit"
    CUSTOM = "custom"


class ModelRoleSettings(BaseModel):
    role: ModelRole
    bundle: ModelProviderBundle = ModelProviderBundle.LOCAL_OPEN_SOURCE
    provider_family: ModelProviderFamily = ModelProviderFamily.OPEN_SOURCE
    provider: ProviderKind = ProviderKind.LOCAL_HTTP
    model: str = DEFAULT_LLM_MODEL
    name: str | None = None
    base_url: str | None = DEFAULT_LLM_BASE_URL
    api_key_env: str | None = None
    timeout_seconds: int = Field(default=DEFAULT_LLM_TIMEOUT_SECONDS, ge=1)
    thinking: ThinkingSetting | None = None
    max_output_tokens: int | None = Field(default=None, ge=1)
    context_budget_tokens: int | None = Field(default=None, ge=1)
    supports_structured_output: bool = True
    supports_tool_use: bool = False
    supports_vision: bool = False
    endpoint_type: str | None = "openai_compatible"
    configured_provider: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def evidence_metadata(self) -> dict[str, Any]:
        return {
            "model_role": self.role.value,
            "model_bundle": self.bundle.value,
            "model_provider_family": self.provider_family.value,
            "provider": self.provider.value,
            "configured_provider": self.configured_provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "timeout_seconds": self.timeout_seconds,
            "thinking": self.thinking,
            "max_output_tokens": self.max_output_tokens,
            "context_budget_tokens": self.context_budget_tokens,
            "supports_structured_output": self.supports_structured_output,
            "supports_tool_use": self.supports_tool_use,
            "supports_vision": self.supports_vision,
            "endpoint_type": self.endpoint_type,
            **self.metadata,
        }
