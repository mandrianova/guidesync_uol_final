from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from .common import Audience, ScreenshotPolicy
from .evidence import EvidenceBundle, EvidenceReference
from .provider import EffectiveModelConfiguration, ProviderConfig, RequestedModelSettings
from .repository import DocumentationInput, RepositoryInput


class ReportConfig(BaseModel):
    output_dir: Path = Path("outputs/latest")
    title: str = "GuideSync release notes"
    formats: list[str] = Field(default_factory=lambda: ["html", "md", "json"])


class GuideSyncRunRequest(BaseModel):
    run_id: str = Field(default_factory=lambda: f"run-{uuid4().hex[:10]}")
    goal: str
    audience: Audience = Audience.END_USERS
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    repositories: list[RepositoryInput] = Field(default_factory=list)
    documentation: list[DocumentationInput] = Field(default_factory=list)
    report: ReportConfig = Field(default_factory=ReportConfig)
    task_interface_url: str | None = None
    screenshot_policy: ScreenshotPolicy = ScreenshotPolicy.DISABLED
    requested_model_settings: RequestedModelSettings | None = None
    effective_model_configuration: EffectiveModelConfiguration | None = None
    project_profile_snapshot_id: str | None = None
    evaluation_notes: str | None = None

    @field_validator("repositories")
    @classmethod
    def require_repo(cls, value: list[RepositoryInput]) -> list[RepositoryInput]:
        if not value:
            raise ValueError("At least one repository is required.")
        return value


class ReviewerCheck(BaseModel):
    name: str
    status: str
    notes: str


class DocumentationEditResult(BaseModel):
    ok: bool = True
    repository_id: str
    docs_path: str
    target_path: str
    changed_docs: list[str] = Field(default_factory=list)
    created_docs: list[str] = Field(default_factory=list)
    updated_docs: list[str] = Field(default_factory=list)
    base_commit: str | None = None
    commit_sha: str | None = None
    commit_message: str | None = None
    patch_artifact_uri: str | None = None
    knowledge_index_run_id: str | None = None
    warnings: list[str] = Field(default_factory=list)


class DocumentationUpdate(BaseModel):
    title: str
    summary: str
    user_facing_change: str
    proposed_update_markdown: str
    evidence_used: list[EvidenceReference]
    reviewer_checks: list[ReviewerCheck]
    documentation_edit: DocumentationEditResult | None = None
    risks_or_limitations: list[str] = Field(default_factory=list)
    suggested_improvements: list[str] = Field(default_factory=list)


class ProviderRunMetadata(BaseModel):
    provider: str
    model: str
    started_at: datetime
    completed_at: datetime
    latency_ms: int
    token_usage: dict[str, Any] = Field(default_factory=dict)
    cost: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ValidationFinding(BaseModel):
    severity: str
    check: str
    message: str
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)


class GuideSyncRunResult(BaseModel):
    run_id: str
    status: str
    request: GuideSyncRunRequest
    evidence: EvidenceBundle
    update: DocumentationUpdate | None = None
    provider_metadata: ProviderRunMetadata | None = None
    findings: list[ValidationFinding] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)


class RunSummary(BaseModel):
    run_id: str
    status: str
    title: str
    created_at: datetime
    updated_at: datetime
    provider: str | None = None
    model: str | None = None
    effective_model_configuration: EffectiveModelConfiguration | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
