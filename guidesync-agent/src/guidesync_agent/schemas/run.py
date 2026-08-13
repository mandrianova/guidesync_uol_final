from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from .common import Audience, ReportLocale, ScreenshotPolicy
from .evidence import EvidenceBundle, EvidenceReference
from .provider import EffectiveModelConfiguration, ProviderConfig
from .repository import DocumentationInput, RepositoryInput
from .video_presentation import VideoPresentationSummary


class ReportConfig(BaseModel):
    output_dir: Path = Path("outputs/latest")
    product_name: str = "GuideSync"
    title: str = "GuideSync release notes"
    locale: ReportLocale = ReportLocale.ENGLISH
    formats: list[str] = Field(default_factory=lambda: ["md", "json"])


class RunContextSources(BaseModel):
    project_profile: bool = True
    knowledge_base: bool = True
    edit_planning: bool = True


class GuideSyncRunRequest(BaseModel):
    run_id: str = Field(default_factory=lambda: f"run-{uuid4().hex[:10]}")
    retry_of_run_id: str | None = None
    goal: str
    audience: Audience = Audience.END_USERS
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    repositories: list[RepositoryInput] = Field(default_factory=list)
    documentation: list[DocumentationInput] = Field(default_factory=list)
    report: ReportConfig = Field(default_factory=ReportConfig)
    task_interface_url: str | None = None
    screenshot_policy: ScreenshotPolicy = ScreenshotPolicy.DISABLED
    effective_model_configuration: EffectiveModelConfiguration | None = None
    project_profile_snapshot_id: str | None = None
    context_sources: RunContextSources = Field(default_factory=RunContextSources)
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


class DocumentationEditOperation(StrEnum):
    UPDATE_SECTION = "update_section"
    ADD_SECTION = "add_section"
    CREATE_DOC = "create_doc"


class DocumentationEditPlanItem(BaseModel):
    id: str
    path: str
    operation: DocumentationEditOperation
    heading: str
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    expected_audience_impact: str = ""


class DocumentationEditPlan(BaseModel):
    id: str
    target_path: str
    docs_path: str
    items: list[DocumentationEditPlanItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentationEditPlanModelOutput(BaseModel):
    """Shallow LLM-facing documentation edit plan output."""

    target_path: str
    docs_path: str
    plan_markdown: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentationEditSection(BaseModel):
    heading: str
    markdown: str


class DocumentationEditStatus(StrEnum):
    COMMITTED = "committed"
    NO_CHANGES = "no_changes"
    PATCH_ONLY = "patch_only"
    FAILED = "failed"


class DocumentationEditResult(BaseModel):
    status: DocumentationEditStatus = DocumentationEditStatus.COMMITTED
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
    edit_plan_artifact_uri: str | None = None
    edit_plan_id: str | None = None
    executed_plan_item_ids: list[str] = Field(default_factory=list)
    knowledge_index_run_id: str | None = None
    annotation_run_ids: list[str] = Field(default_factory=list)
    annotation_warnings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentationUpdateChange(BaseModel):
    id: str
    title: str
    summary: str
    user_facing_change: str
    how_to_markdown: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class ReleaseScreenshotRequest(BaseModel):
    id: str
    change_id: str
    claim: str
    purpose: str
    route_hint: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class DocumentationUpdate(BaseModel):
    title: str
    summary: str
    user_facing_change: str
    proposed_update_markdown: str
    evidence_used: list[EvidenceReference]
    reviewer_checks: list[ReviewerCheck]
    changes: list[DocumentationUpdateChange] = Field(default_factory=list)
    screenshot_requests: list[ReleaseScreenshotRequest] = Field(default_factory=list)
    documentation_edit: DocumentationEditResult | None = None
    risks_or_limitations: list[str] = Field(default_factory=list)
    suggested_improvements: list[str] = Field(default_factory=list)


class DocumentationUpdateModelOutput(BaseModel):
    """Shallow LLM-facing documentation/release update output.

    Rich repeated prose belongs in Markdown strings. Backend workflow code
    converts evidence refs and review notes into the richer internal model.
    """

    title: str
    summary: str
    user_facing_change: str
    proposed_update_markdown: str
    evidence_refs: list[str] = Field(default_factory=list)
    reviewer_notes: str = ""
    risks_or_limitations: list[str] = Field(default_factory=list)
    suggested_improvements: list[str] = Field(default_factory=list)
    change_ids: list[str] = Field(default_factory=list)
    change_titles: list[str] = Field(default_factory=list)
    change_summaries: list[str] = Field(default_factory=list)
    change_user_facing_details: list[str] = Field(default_factory=list)
    change_how_to_markdown: list[str] = Field(default_factory=list)
    change_evidence_refs: list[str] = Field(default_factory=list)
    screenshot_change_ids: list[str] = Field(default_factory=list, max_length=4)
    screenshot_claims: list[str] = Field(default_factory=list, max_length=4)
    screenshot_purposes: list[str] = Field(default_factory=list, max_length=4)
    screenshot_route_hints: list[str] = Field(default_factory=list, max_length=4)
    screenshot_evidence_refs: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_parallel_change_fields(self) -> DocumentationUpdateModelOutput:
        lengths = {
            len(self.change_ids),
            len(self.change_titles),
            len(self.change_summaries),
            len(self.change_user_facing_details),
            len(self.change_how_to_markdown),
            len(self.change_evidence_refs),
        }
        if lengths != {0} and len(lengths) != 1:
            raise ValueError("Parallel release-note change fields must have equal lengths.")
        screenshot_lengths = {
            len(self.screenshot_change_ids),
            len(self.screenshot_claims),
            len(self.screenshot_purposes),
            len(self.screenshot_route_hints),
            len(self.screenshot_evidence_refs),
        }
        if screenshot_lengths != {0} and len(screenshot_lengths) != 1:
            raise ValueError("Parallel screenshot request fields must have equal lengths.")
        unknown_change_ids = set(self.screenshot_change_ids).difference(self.change_ids)
        if unknown_change_ids:
            raise ValueError(
                "Screenshot requests must use a reported change id: "
                + ", ".join(sorted(unknown_change_ids))
            )
        return self


class ReleaseNotesChunkSummary(BaseModel):
    summary: str
    user_facing_changes: list[str] = Field(default_factory=list)
    release_note_candidates: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    chunk: int | None = None


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
    video_presentation: VideoPresentationSummary = Field(
        default_factory=VideoPresentationSummary
    )

class RunCancellationResult(BaseModel):
    run: GuideSyncRunResult
    cancelled_task_ids: list[str] = Field(default_factory=list)
    preserved_completed_task_ids: list[str] = Field(default_factory=list)
    cancelled_transcript_ids: list[str] = Field(default_factory=list)


class RunSummary(BaseModel):
    run_id: str
    status: str
    title: str
    created_at: datetime
    updated_at: datetime
    provider: str | None = None
    model: str | None = None
    effective_model_configuration: EffectiveModelConfiguration | None = None
    publication_available: bool = False
    artifacts: dict[str, str] = Field(default_factory=dict)
    video_presentation: VideoPresentationSummary = Field(
        default_factory=VideoPresentationSummary
    )
