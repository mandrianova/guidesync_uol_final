from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .repository import RepositorySyncTask
from .run import RunSummary
from .tools import ChangedFileRef, FileChangeSummary
from .video_presentation import (
    VideoAudioSegment,
    VideoPresentationPlan,
    VideoPresentationSummary,
    VideoSlideArtifact,
)


class ProjectWorkflowTaskKind(StrEnum):
    REPOSITORY_SYNC = "repository_sync"
    PROJECT_PROFILE = "project_profile"
    KNOWLEDGE_INDEX = "knowledge_index"
    CHANGE_ANALYSIS_PLAN = "change_analysis_plan"
    CHANGE_ANALYSIS = "change_analysis_orchestration"
    CHANGE_ANALYSIS_UNIT = "change_analysis_unit"
    CHANGE_SYNTHESIS = "change_synthesis"
    SCREENSHOT_CAPTURE = "screenshot_capture"
    POST_ANALYSIS_KNOWLEDGE_REFRESH = "post_analysis_knowledge_refresh"
    VIDEO_PRESENTATION = "video_presentation"
    RETIRED_CHANGE_ANALYSIS = "change_analysis"


class ProjectWorkflowTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class ProjectWorkflowStage(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PLANNING = "planning"
    PREPARING_CONTEXT = "preparing_context"
    ANALYZING = "analyzing"
    SYNTHESIZING = "synthesizing"
    CAPTURING_SCREENSHOTS = "capturing_screenshots"
    REFRESHING_KNOWLEDGE = "refreshing_knowledge"
    GENERATING_PRESENTATION = "generating_presentation"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProjectWorkflowProgress(BaseModel):
    stage: ProjectWorkflowStage = ProjectWorkflowStage.QUEUED
    message: str = "Queued"
    completed_items: int = Field(default=0, ge=0)
    total_items: int | None = Field(default=None, ge=0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectWorkflowRequestedBy(StrEnum):
    SYSTEM = "system"
    USER = "user"
    API = "api"


class RepositorySyncWorkflowInput(BaseModel):
    kind: Literal[ProjectWorkflowTaskKind.REPOSITORY_SYNC] = ProjectWorkflowTaskKind.REPOSITORY_SYNC
    repository_ids: list[str] = Field(default_factory=list)


class ProjectProfileWorkflowInput(BaseModel):
    kind: Literal[ProjectWorkflowTaskKind.PROJECT_PROFILE] = ProjectWorkflowTaskKind.PROJECT_PROFILE
    profile_id: str | None = None


class KnowledgeIndexWorkflowInput(BaseModel):
    kind: Literal[ProjectWorkflowTaskKind.KNOWLEDGE_INDEX] = ProjectWorkflowTaskKind.KNOWLEDGE_INDEX
    max_file_bytes: int = Field(default=200_000, ge=1, le=2_000_000)


class ChangeAnalysisWorkUnit(BaseModel):
    id: str
    repository_id: str
    files: list[ChangedFileRef] = Field(min_length=1)
    base_ref: str | None = None
    head_ref: str = "HEAD"
    grouping_reason: str
    connectivity_evidence: list[str] = Field(default_factory=list)


class ChangeAnalysisInventoryItemKind(StrEnum):
    COMMIT = "commit"
    PATH = "path"


class ChangeAnalysisInventoryItem(BaseModel):
    key: str
    kind: ChangeAnalysisInventoryItemKind
    repository_id: str
    summary: str
    path: str | None = None
    status: str | None = None
    commit_sha: str | None = None
    related_paths: list[str] = Field(default_factory=list)
    base_ref: str | None = None
    head_ref: str = "HEAD"


class ChangeAnalysisInventory(BaseModel):
    run_id: str
    items: list[ChangeAnalysisInventoryItem] = Field(default_factory=list)


class ReleaseChangeKind(StrEnum):
    FEATURE = "feature"
    FIX = "fix"
    BREAKING = "breaking"
    SECURITY = "security"
    PERFORMANCE = "performance"
    DOCUMENTATION = "documentation"
    INTERNAL = "internal"


class ReleaseChangeConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReleaseChangeFinding(BaseModel):
    id: str
    title: str
    kind: ReleaseChangeKind
    technical_summary: str
    user_impact: str
    coverage_keys: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    documentation_search_intents: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    release_note_eligible: bool = True
    confidence: ReleaseChangeConfidence = ReleaseChangeConfidence.MEDIUM
    artifact_ref: str | None = None


class ChangeAnalysisCoverageDisposition(StrEnum):
    FINDING = "finding"
    NO_RELEASE_NOTE = "no_release_note"
    UNRESOLVED = "unresolved"


class ChangeAnalysisCoverage(BaseModel):
    key: str
    disposition: ChangeAnalysisCoverageDisposition
    finding_id: str | None = None
    reason: str = ""


class ChangeAnalysisCheckpoint(BaseModel):
    findings: list[ReleaseChangeFinding] = Field(default_factory=list)
    coverage: list[ChangeAnalysisCoverage] = Field(default_factory=list)
    summary: str = ""
    transcript_ids: list[str] = Field(default_factory=list)
    completed: bool = False


class AnalysisArtifactDigest(BaseModel):
    technical_summary: str = ""
    product_impact: str = ""
    affected_components: list[str] = Field(default_factory=list)
    affected_workflows: list[str] = Field(default_factory=list)
    documentation_search_intents: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    needs_main_agent_review: bool = False


class AnalysisArtifactRef(BaseModel):
    id: str
    work_unit_id: str
    repository_id: str
    path: str
    artifact_ref: str
    digest: AnalysisArtifactDigest = Field(default_factory=AnalysisArtifactDigest)


class AnalysisArtifactManifest(BaseModel):
    run_id: str
    plan_task_id: str
    planned_paths: list[str] = Field(default_factory=list)
    completed_unit_ids: list[str] = Field(default_factory=list)
    failed_unit_ids: list[str] = Field(default_factory=list)
    artifacts: list[AnalysisArtifactRef] = Field(default_factory=list)
    findings: list[ReleaseChangeFinding] = Field(default_factory=list)
    coverage: list[ChangeAnalysisCoverage] = Field(default_factory=list)


class ChangeAnalysisPlanWorkflowInput(BaseModel):
    kind: Literal[ProjectWorkflowTaskKind.CHANGE_ANALYSIS_PLAN] = (
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS_PLAN
    )
    run_id: str


class ChangeAnalysisWorkflowInput(BaseModel):
    kind: Literal[ProjectWorkflowTaskKind.CHANGE_ANALYSIS] = (
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS
    )
    run_id: str
    plan_task_id: str


class RetiredChangeAnalysisWorkflowInput(BaseModel):
    """Read-only contract for persisted tasks created before durable orchestration."""

    kind: Literal[ProjectWorkflowTaskKind.RETIRED_CHANGE_ANALYSIS] = (
        ProjectWorkflowTaskKind.RETIRED_CHANGE_ANALYSIS
    )
    run_id: str


class ChangeAnalysisUnitWorkflowInput(BaseModel):
    kind: Literal[ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT] = (
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT
    )
    run_id: str
    work_unit: ChangeAnalysisWorkUnit


class ChangeSynthesisWorkflowInput(BaseModel):
    kind: Literal[ProjectWorkflowTaskKind.CHANGE_SYNTHESIS] = (
        ProjectWorkflowTaskKind.CHANGE_SYNTHESIS
    )
    run_id: str
    plan_task_id: str
    analysis_task_id: str | None = None
    unit_task_ids: list[str] = Field(default_factory=list)


class ScreenshotCaptureWorkflowInput(BaseModel):
    kind: Literal[ProjectWorkflowTaskKind.SCREENSHOT_CAPTURE] = (
        ProjectWorkflowTaskKind.SCREENSHOT_CAPTURE
    )
    run_id: str
    synthesis_task_id: str | None = None
    regenerate: bool = False


class PostAnalysisKnowledgeRefreshInput(BaseModel):
    kind: Literal[ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH] = (
        ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH
    )
    run_id: str
    changed_docs: list[str] = Field(default_factory=list)


class VideoPresentationWorkflowInput(BaseModel):
    kind: Literal[ProjectWorkflowTaskKind.VIDEO_PRESENTATION] = (
        ProjectWorkflowTaskKind.VIDEO_PRESENTATION
    )
    run_id: str
    regenerate: bool = False


ProjectWorkflowTaskInput = Annotated[
    RepositorySyncWorkflowInput
    | ProjectProfileWorkflowInput
    | KnowledgeIndexWorkflowInput
    | ChangeAnalysisPlanWorkflowInput
    | ChangeAnalysisWorkflowInput
    | ChangeAnalysisUnitWorkflowInput
    | ChangeSynthesisWorkflowInput
    | ScreenshotCaptureWorkflowInput
    | PostAnalysisKnowledgeRefreshInput
    | VideoPresentationWorkflowInput
    | RetiredChangeAnalysisWorkflowInput,
    Field(discriminator="kind"),
]


class RepositorySyncWorkflowResult(BaseModel):
    repository_tasks: list[RepositorySyncTask] = Field(default_factory=list)


class ProjectProfileWorkflowResult(BaseModel):
    profile_snapshot_id: str | None = None


class KnowledgeIndexWorkflowResult(BaseModel):
    knowledge_index_run_id: str | None = None


class ChangeAnalysisPlanWorkflowResult(BaseModel):
    inventory: ChangeAnalysisInventory | None = None
    analysis_task_id: str | None = None
    work_units: list[ChangeAnalysisWorkUnit] = Field(default_factory=list)
    unit_task_ids: list[str] = Field(default_factory=list)
    synthesis_task_id: str | None = None
    refresh_task_id: str | None = None
    manifest_artifact_ref: str | None = None


class ChangeAnalysisUnitWorkflowResult(BaseModel):
    work_unit_id: str
    file_summaries: list[FileChangeSummary] = Field(default_factory=list)


class ChangeAnalysisWorkflowResult(BaseModel):
    inventory: ChangeAnalysisInventory
    checkpoint: ChangeAnalysisCheckpoint = Field(default_factory=ChangeAnalysisCheckpoint)
    report_run_id: str | None = None


class ChangeSynthesisWorkflowResult(BaseModel):
    report_run_id: str | None = None
    screenshot_task_id: str | None = None


class ScreenshotCaptureWorkflowResult(BaseModel):
    report_run_id: str
    request_count: int = 0
    capture_count: int = 0
    approved_count: int = 0
    transcript_id: str | None = None
    summary: str = ""


class RetiredChangeAnalysisWorkflowResult(BaseModel):
    report_run_id: str | None = None


class PostAnalysisKnowledgeRefreshResult(BaseModel):
    knowledge_index_run_id: str | None = None
    annotation_run_ids: list[str] = Field(default_factory=list)


class VideoPresentationWorkflowResult(BaseModel):
    plan: VideoPresentationPlan | None = None
    presentation: VideoPresentationSummary
    slides: list[VideoSlideArtifact] = Field(default_factory=list)
    audio_segments: list[VideoAudioSegment] = Field(default_factory=list)


ProjectWorkflowTaskResult = (
    RepositorySyncWorkflowResult
    | ProjectProfileWorkflowResult
    | KnowledgeIndexWorkflowResult
    | ChangeAnalysisPlanWorkflowResult
    | ChangeAnalysisWorkflowResult
    | ChangeAnalysisUnitWorkflowResult
    | ChangeSynthesisWorkflowResult
    | ScreenshotCaptureWorkflowResult
    | PostAnalysisKnowledgeRefreshResult
    | VideoPresentationWorkflowResult
    | RetiredChangeAnalysisWorkflowResult
    | None
)


class ProjectWorkflowTask(BaseModel):
    id: str = Field(default_factory=lambda: f"workflow-task-{uuid4().hex[:10]}")
    project_id: str
    kind: ProjectWorkflowTaskKind
    status: ProjectWorkflowTaskStatus = ProjectWorkflowTaskStatus.QUEUED
    sequence: int = Field(default=0, ge=0)
    depends_on_task_ids: list[str] = Field(default_factory=list)
    dedupe_key: str | None = None
    requested_by: ProjectWorkflowRequestedBy = ProjectWorkflowRequestedBy.API
    reason: str = ""
    input: ProjectWorkflowTaskInput
    result: ProjectWorkflowTaskResult = None
    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=2, ge=1)
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    progress: ProjectWorkflowProgress = Field(default_factory=ProjectWorkflowProgress)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ProjectWorkflowPlan(BaseModel):
    project_id: str
    tasks: list[ProjectWorkflowTask] = Field(default_factory=list)
    run: RunSummary | None = None
    warnings: list[str] = Field(default_factory=list)


class ProjectPipelineState(BaseModel):
    project_id: str
    profile_ready: bool = False
    knowledge_base_ready: bool = False
    blocked_reason: str | None = None
    tasks: list[ProjectWorkflowTask] = Field(default_factory=list)
