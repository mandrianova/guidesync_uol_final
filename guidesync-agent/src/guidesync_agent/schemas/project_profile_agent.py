from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .common import Audience, RepositoryCacheStatus
from .project import (
    ProjectProfileEvidenceRef,
    ProjectProfileRepositoryMapItem,
    ProjectProfileSourceRef,
    ProjectTaxonomy,
)
from .run import ValidationFinding
from .tools import RepositoryFileWindow, RepositorySearchResult, ToolError, ToolPagination


class ProjectProfileBuildReason(StrEnum):
    PROJECT_CREATED = "project_created"
    PROJECT_UPDATED = "project_updated"
    MANUAL_REBUILD = "manual_rebuild"
    WORKFLOW_PREREQUISITE = "workflow_prerequisite"
    TEST = "test"


class ProjectProfileToolBudget(BaseModel):
    max_tool_calls: int = Field(default=24, ge=1)
    max_file_window_chars: int = Field(default=12_000, ge=1)
    max_total_evidence_chars: int = Field(default=60_000, ge=1)
    file_listing_page_size: int = Field(default=400, ge=1)


class ProjectProfileRepositorySummary(BaseModel):
    project_id: str
    repository_id: str
    name: str
    url: str
    default_branch: str | None = None
    current_commit: str | None = None
    cache_status: RepositoryCacheStatus
    local_path: str | None = None
    analysis_paths: list[str] = Field(default_factory=list)
    knowledge_base_path: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ProjectProfileFileRef(BaseModel):
    repository_id: str
    path: str
    size_bytes: int = 0
    suffix: str = ""
    evidence_ref: str


class ProjectProfileFileListing(BaseModel):
    ok: bool = True
    project_id: str
    repository_id: str
    files: list[ProjectProfileFileRef] = Field(default_factory=list)
    pagination: ToolPagination
    error: ToolError | None = None


class ProjectProfileSelectedFile(BaseModel):
    repository_id: str
    path: str
    reason: str = ""


class ProjectProfileSearchQuery(BaseModel):
    repository_id: str
    query: str
    path_filters: list[str] = Field(default_factory=list)
    reason: str = ""


class ProjectProfileFileSelection(BaseModel):
    files_to_read: list[ProjectProfileSelectedFile] = Field(default_factory=list)
    search_queries: list[ProjectProfileSearchQuery] = Field(default_factory=list)
    reasoning_summary: str = ""
    warnings: list[str] = Field(default_factory=list)


class ProjectProfileToolTraceRef(BaseModel):
    tool_name: str
    repository_id: str | None = None
    input_summary: str = ""
    output_summary: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_ref: str | None = None
    error: ToolError | None = None


class ProjectProfileAgentEvidence(BaseModel):
    repository_summaries: list[ProjectProfileRepositorySummary] = Field(default_factory=list)
    file_listings: list[ProjectProfileFileListing] = Field(default_factory=list)
    file_windows: list[RepositoryFileWindow] = Field(default_factory=list)
    search_results: list[RepositorySearchResult] = Field(default_factory=list)
    tool_trace: list[ProjectProfileToolTraceRef] = Field(default_factory=list)


class ProjectProfileAgentRequest(BaseModel):
    project_id: str
    profile_id: str
    reason: ProjectProfileBuildReason
    name: str
    description: str | None = None
    audience: Audience
    documentation_instructions: str = ""
    knowledge_base_repository_id: str | None = None
    knowledge_base_ref: str | None = None
    knowledge_base_path: str = "docs/"
    analysis_paths: list[str] = Field(default_factory=list)
    repositories: list[ProjectProfileRepositorySummary] = Field(default_factory=list)
    budget: ProjectProfileToolBudget = Field(default_factory=ProjectProfileToolBudget)
    previous_profile_id: str | None = None


class ProjectProfileAgentOutput(BaseModel):
    summary: str = ""
    architecture: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
    taxonomy: ProjectTaxonomy = Field(default_factory=ProjectTaxonomy)
    profile_evidence: list[ProjectProfileEvidenceRef] = Field(default_factory=list)
    repository_map: list[ProjectProfileRepositoryMapItem] = Field(default_factory=list)
    source_refs: list[ProjectProfileSourceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    model_metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectProfileAgentResult(BaseModel):
    output: ProjectProfileAgentOutput
    selection: ProjectProfileFileSelection
    evidence: ProjectProfileAgentEvidence
    validation_findings: list[ValidationFinding] = Field(default_factory=list)
    provider: str
    model: str
    model_metadata: dict[str, Any] = Field(default_factory=dict)
