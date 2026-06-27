from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from .model_roles import ModelProviderFamily, ModelRole


class ModelSmokeStatus(StrEnum):
    PLANNED = "planned"
    SKIPPED = "skipped"
    PASSED = "passed"
    FAILED = "failed"


class ModelSmokeRequest(BaseModel):
    roles: list[ModelRole] = Field(default_factory=list)
    execute: bool = False
    strict: bool = False
    output_path: Path | None = None
    screenshot_path: Path | None = None


class ModelSmokeRoleResult(BaseModel):
    role: ModelRole
    status: ModelSmokeStatus
    provider: str
    model: str
    provider_family: ModelProviderFamily
    base_url: str | None = None
    timeout_seconds: int
    api_key_env: str | None = None
    role_profile_override: bool = False
    structured_output_mode: str | None = None
    response_excerpt: str | None = None
    artifact_path: str | None = None
    skipped_reason: str | None = None
    error_message: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class ModelSmokeReport(BaseModel):
    generated_at: datetime
    execute: bool
    strict: bool
    results: list[ModelSmokeRoleResult]
    warnings: list[str] = Field(default_factory=list)
