from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .repository import RepositorySyncTask
from .run import RunSummary


class ProjectWorkflowTaskKind(StrEnum):
    REPOSITORY_SYNC = "repository_sync"
    PROJECT_PROFILE = "project_profile"
    KNOWLEDGE_INDEX = "knowledge_index"
    CHANGE_ANALYSIS = "change_analysis"
    POST_ANALYSIS_KNOWLEDGE_REFRESH = "post_analysis_knowledge_refresh"


class ProjectWorkflowTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


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


class ChangeAnalysisWorkflowInput(BaseModel):
    kind: Literal[ProjectWorkflowTaskKind.CHANGE_ANALYSIS] = ProjectWorkflowTaskKind.CHANGE_ANALYSIS
    run_id: str


class PostAnalysisKnowledgeRefreshInput(BaseModel):
    kind: Literal[
        ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH
    ] = ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH
    run_id: str
    changed_docs: list[str] = Field(default_factory=list)


ProjectWorkflowTaskInput = Annotated[
    RepositorySyncWorkflowInput
    | ProjectProfileWorkflowInput
    | KnowledgeIndexWorkflowInput
    | ChangeAnalysisWorkflowInput
    | PostAnalysisKnowledgeRefreshInput,
    Field(discriminator="kind"),
]


class RepositorySyncWorkflowResult(BaseModel):
    repository_tasks: list[RepositorySyncTask] = Field(default_factory=list)


class ProjectProfileWorkflowResult(BaseModel):
    profile_snapshot_id: str | None = None


class KnowledgeIndexWorkflowResult(BaseModel):
    knowledge_index_run_id: str | None = None


class ChangeAnalysisWorkflowResult(BaseModel):
    report_run_id: str | None = None


class PostAnalysisKnowledgeRefreshResult(BaseModel):
    knowledge_index_run_id: str | None = None
    annotation_run_ids: list[str] = Field(default_factory=list)


ProjectWorkflowTaskResult = (
    RepositorySyncWorkflowResult
    | ProjectProfileWorkflowResult
    | KnowledgeIndexWorkflowResult
    | ChangeAnalysisWorkflowResult
    | PostAnalysisKnowledgeRefreshResult
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
