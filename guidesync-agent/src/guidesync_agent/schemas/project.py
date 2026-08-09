from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field

from .common import (
    Audience,
    ProjectProfileStatus,
    ReportLocale,
    RepositoryCacheStatus,
    RunMode,
    ScreenshotPolicy,
)
from .run import ValidationFinding


class ProjectTaxonomyBootstrapStatus(StrEnum):
    SELECTED = "selected"
    REJECTED = "rejected"
    CANDIDATE = "candidate"


class ProjectTaxonomyCandidateKind(StrEnum):
    DOMAIN_TERM = "domain_term"


class ProjectTaxonomyEvidenceKind(StrEnum):
    CATEGORY = "category"
    COMPONENT = "component"
    WORKFLOW = "workflow"
    DOCUMENTATION_AREA = "documentation_area"
    DOMAIN_TERM = "domain_term"
    ALIAS = "alias"
    BOOTSTRAP_HINT = "bootstrap_hint"


class ProjectRepository(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: f"repo-{uuid4().hex[:10]}")
    name: str
    url: str
    default_branch: str | None = None
    analysis_paths: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("analysis_paths", "paths"),
    )
    credential_ref: str | None = None
    cache_status: RepositoryCacheStatus = RepositoryCacheStatus.NOT_SYNCED
    local_path: str | None = None
    current_commit: str | None = None
    cache_warnings: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def paths(self) -> list[str]:
        return self.analysis_paths


class ProjectDocumentation(BaseModel):
    id: str = Field(default_factory=lambda: f"doc-{uuid4().hex[:10]}")
    name: str
    description: str | None = None
    path: str | None = None


class ProjectConfig(BaseModel):
    id: str = Field(default_factory=lambda: f"project-{uuid4().hex[:10]}")
    name: str
    description: str | None = None
    audience: Audience = Audience.END_USERS
    documentation_instructions: str = ""
    knowledge_base_repository_id: str | None = None
    knowledge_base_ref: str | None = None
    knowledge_base_path: str = "docs/"
    analysis_paths: list[str] = Field(default_factory=list)
    credential_ref: str | None = None
    repositories: list[ProjectRepository] = Field(default_factory=list)
    documentation: list[ProjectDocumentation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectProfileSourceRef(BaseModel):
    repository_id: str
    repository_name: str
    ref: str | None = None
    commit_sha: str | None = None
    local_path: str | None = None
    docs_path: str | None = None
    analysis_paths: list[str] = Field(default_factory=list)


class ProjectProfileRepositoryMapItem(BaseModel):
    repository_id: str
    name: str
    url: str
    default_branch: str | None = None
    current_commit: str | None = None
    cache_status: RepositoryCacheStatus = RepositoryCacheStatus.NOT_SYNCED
    analysis_paths: list[str] = Field(default_factory=list)
    knowledge_base_path: str | None = None


class ProjectTaxonomyAlias(BaseModel):
    canonical: str
    aliases: list[str] = Field(default_factory=list)


class ProjectTaxonomyAudienceTerm(BaseModel):
    audience: Audience
    preferred: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class ProjectTaxonomyBootstrapHint(BaseModel):
    value: str
    status: ProjectTaxonomyBootstrapStatus = ProjectTaxonomyBootstrapStatus.CANDIDATE
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class ProjectTaxonomyCandidateTerm(BaseModel):
    value: str
    kind: ProjectTaxonomyCandidateKind
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class ProjectTaxonomyEvidenceRef(BaseModel):
    value: str
    kind: ProjectTaxonomyEvidenceKind
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class ProjectTaxonomy(BaseModel):
    version: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    categories: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    documentation_areas: list[str] = Field(default_factory=list)
    domain_terms: list[str] = Field(default_factory=list)
    aliases: list[ProjectTaxonomyAlias] = Field(default_factory=list)
    audience_terms: list[ProjectTaxonomyAudienceTerm] = Field(default_factory=list)
    bootstrap_hints: list[ProjectTaxonomyBootstrapHint] = Field(default_factory=list)
    candidate_terms: list[ProjectTaxonomyCandidateTerm] = Field(default_factory=list)
    evidence_refs: list[ProjectTaxonomyEvidenceRef] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)


class ProjectProfileEvidenceRef(BaseModel):
    path: str
    reason: str
    repository_id: str | None = None
    line: int | None = None


class ProjectProfileSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: f"profile-{uuid4().hex[:10]}")
    project_id: str
    status: ProjectProfileStatus = ProjectProfileStatus.QUEUED
    version: int = Field(default=1, ge=1)
    prompt_version: str
    summary: str = ""
    project_description: str = ""
    project_structure: list[str] = Field(default_factory=list)
    architecture: list[str] = Field(default_factory=list)
    core_concepts: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
    agent_context: str = ""
    taxonomy: ProjectTaxonomy = Field(default_factory=ProjectTaxonomy)
    profile_evidence: list[ProjectProfileEvidenceRef] = Field(default_factory=list)
    repository_map: list[ProjectProfileRepositoryMapItem] = Field(default_factory=list)
    source_refs: list[ProjectProfileSourceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    artifact_uris: dict[str, str] = Field(default_factory=dict)
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    tool_trace_refs: list[str] = Field(default_factory=list)
    validation_findings: list[ValidationFinding] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    error_message: str | None = None


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    audience: Audience = Audience.END_USERS
    documentation_instructions: str = ""
    knowledge_base_repository_id: str | None = None
    knowledge_base_ref: str | None = None
    knowledge_base_path: str = "docs/"
    analysis_paths: list[str] = Field(default_factory=list)
    credential_ref: str | None = None
    repositories: list[ProjectRepository] = Field(default_factory=list)
    documentation: list[ProjectDocumentation] = Field(default_factory=list)


class ProjectRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: RunMode = RunMode.DEFAULT_BRANCH_PERIOD
    goal: str
    since: str | None = None
    until: str | None = None
    branches: dict[str, list[str]] = Field(default_factory=dict)
    max_commits: int = Field(default=40, ge=1, le=500)
    audience: Audience | None = None
    task_interface_url: str | None = None
    screenshot_policy: ScreenshotPolicy = ScreenshotPolicy.DISABLED
    report_locale: ReportLocale = ReportLocale.ENGLISH
    project_profile_snapshot_id: str | None = None
