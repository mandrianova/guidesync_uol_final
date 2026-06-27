from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .common import ProviderKind
from .model_roles import ModelRole


class ModelCallStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TokenUsageSource(StrEnum):
    PROVIDER_REPORTED = "provider_reported"
    LOCAL_ESTIMATE = "local_estimate"
    MIXED = "mixed"
    NOT_AVAILABLE = "not_available"


class TokenUsageBreakdown(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)
    image_input_tokens: int | None = Field(default=None, ge=0)
    image_input_units: int | None = Field(default=None, ge=0)
    embedding_input_tokens: int | None = Field(default=None, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    model_turn_count: int = Field(default=1, ge=0)
    context_compaction_input_tokens: int | None = Field(default=None, ge=0)
    context_compaction_output_tokens: int | None = Field(default=None, ge=0)
    provider_reported_total_tokens: int | None = Field(default=None, ge=0)
    locally_estimated_total_tokens: int | None = Field(default=None, ge=0)


class ModelCallLedgerEntry(BaseModel):
    id: str
    project_id: str | None = None
    run_id: str | None = None
    workflow_task_id: str | None = None
    parent_call_id: str | None = None
    role: ModelRole
    provider: ProviderKind
    model: str
    model_profile_id: str | None = None
    endpoint_type: str | None = None
    base_url_host_hash: str | None = None
    deployment_id: str | None = None
    prompt_version: str | None = None
    structured_output_schema: str | None = None
    status: ModelCallStatus = ModelCallStatus.COMPLETED
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    usage_source: TokenUsageSource = TokenUsageSource.NOT_AVAILABLE
    usage: TokenUsageBreakdown = Field(default_factory=TokenUsageBreakdown)
    request_artifact_ref: str | None = None
    response_artifact_ref: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class TokenUsageSummaryItem(BaseModel):
    key: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_tokens: int = 0
    calls: int = 0
    warnings: list[str] = Field(default_factory=list)


class RunTokenUsageSummary(BaseModel):
    run_id: str
    total_tokens: int = 0
    estimated_tokens: int = 0
    calls: int = 0
    by_workflow_task: list[TokenUsageSummaryItem] = Field(default_factory=list)
    by_role: list[TokenUsageSummaryItem] = Field(default_factory=list)
    by_provider: list[TokenUsageSummaryItem] = Field(default_factory=list)
    by_model: list[TokenUsageSummaryItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WorkflowTaskTokenUsageSummary(BaseModel):
    workflow_task_id: str
    run_ids: list[str] = Field(default_factory=list)
    total_tokens: int = 0
    estimated_tokens: int = 0
    calls: int = 0
    by_role: list[TokenUsageSummaryItem] = Field(default_factory=list)
    by_provider: list[TokenUsageSummaryItem] = Field(default_factory=list)
    by_model: list[TokenUsageSummaryItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
