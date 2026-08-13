from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from guidesync_agent.schemas.project_cleanup import (
    ProjectCleanupArtifact,
    ProjectCleanupResourceCount,
    ProjectCleanupState,
)


class RunCleanupRequest(BaseModel):
    target_run_ids: list[str] = Field(min_length=1)
    protected_run_ids: list[str] = Field(default_factory=list)

    @field_validator("target_run_ids")
    @classmethod
    def normalize_target_run_ids(cls, value: list[str]) -> list[str]:
        normalized = normalize_run_ids(value)
        if not normalized:
            raise ValueError("At least one non-empty target run id is required.")
        return normalized

    @field_validator("protected_run_ids")
    @classmethod
    def normalize_protected_run_ids(cls, value: list[str]) -> list[str]:
        return normalize_run_ids(value)

    @model_validator(mode="after")
    def reject_protected_targets(self) -> RunCleanupRequest:
        overlap = sorted(set(self.target_run_ids) & set(self.protected_run_ids))
        if overlap:
            raise ValueError("Protected runs cannot be cleanup targets: " + ", ".join(overlap))
        return self


def normalize_run_ids(value: list[str]) -> list[str]:
    return sorted({run_id.strip() for run_id in value if run_id.strip()})


class RunCleanupRun(BaseModel):
    run_id: str
    project_id: str | None = None
    status: str | None = None
    state: ProjectCleanupState
    publication_available: bool = False
    artifacts: list[ProjectCleanupArtifact] = Field(default_factory=list)
    s3_keys: list[str] = Field(default_factory=list)
    active_workflow_task_ids: list[str] = Field(default_factory=list)
    evaluation_reference_ids: list[str] = Field(default_factory=list)
    resource_counts: list[ProjectCleanupResourceCount] = Field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(
            self.publication_available
            or self.active_workflow_task_ids
            or self.evaluation_reference_ids
            or self.status not in {"cancelled", "completed", "failed", "partial_failure", None}
        )


class RunCleanupPlan(BaseModel):
    schema_version: str = "1.0"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    artifact_bucket: str
    artifact_endpoint_url: str | None = None
    artifact_prefix: str
    target_run_ids: list[str]
    protected_run_ids: list[str]
    runs: list[RunCleanupRun]
    checksum: str = ""

    @property
    def safe_to_apply(self) -> bool:
        return not any(run.blocked for run in self.runs)


class RunCleanupApplyResult(BaseModel):
    plan_checksum: str
    deleted_run_ids: list[str] = Field(default_factory=list)
    already_absent_run_ids: list[str] = Field(default_factory=list)
    database_counts: list[ProjectCleanupResourceCount] = Field(default_factory=list)
    deleted_s3_keys: list[str] = Field(default_factory=list)
    external_errors: list[str] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.external_errors
