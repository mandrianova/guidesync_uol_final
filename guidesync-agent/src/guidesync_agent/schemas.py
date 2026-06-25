from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field, field_validator

from guidesync_agent.llm.settings import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TIMEOUT_SECONDS,
)


class ProviderKind(StrEnum):
    MOCK = "mock"
    PYDANTIC_AI = "pydantic_ai"
    LOCAL_HTTP = "local_http"


class RunMode(StrEnum):
    DEFAULT_BRANCH_PERIOD = "default_branch_period"
    SELECT_BRANCHES = "select_branches"


class Audience(StrEnum):
    DEVELOPERS = "developers"
    END_USERS = "end_users"
    BUSINESS_ANALYSTS = "business_analysts"


class ScreenshotPolicy(StrEnum):
    DISABLED = "disabled"
    OPTIONAL = "optional"
    REQUIRED = "required"


class RepositoryCacheStatus(StrEnum):
    NOT_SYNCED = "not_synced"
    SYNCING = "syncing"
    READY = "ready"
    FAILED = "failed"


ThinkingSetting = bool | Literal["minimal", "low", "medium", "high", "xhigh"]


class ProviderConfig(BaseModel):
    provider: ProviderKind = ProviderKind.PYDANTIC_AI
    model: str = DEFAULT_LLM_MODEL
    name: str | None = None
    base_url: str | None = DEFAULT_LLM_BASE_URL
    api_key_env: str | None = None
    api_key: str | None = Field(default=None, exclude=True)
    timeout_seconds: int = Field(default=DEFAULT_LLM_TIMEOUT_SECONDS, ge=1)
    thinking: ThinkingSetting | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelSettings(BaseModel):
    id: str = "global-default"
    name: str = "Default model"
    provider: ProviderKind = ProviderKind.PYDANTIC_AI
    model: str = DEFAULT_LLM_MODEL
    base_url: str | None = DEFAULT_LLM_BASE_URL
    api_key: str | None = Field(default=None, exclude=True)
    has_api_key: bool = False
    is_default: bool = True
    timeout_seconds: int = Field(default=DEFAULT_LLM_TIMEOUT_SECONDS, ge=1)
    thinking: ThinkingSetting | None = None


class ModelSettingsUpdate(BaseModel):
    name: str | None = None
    provider: ProviderKind
    model: str
    base_url: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    timeout_seconds: int = Field(default=60, ge=1)
    thinking: ThinkingSetting | None = None


class RequestedModelSettings(BaseModel):
    model_profile_id: str | None = None
    provider: ProviderKind | None = None
    model: str | None = None
    base_url: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    thinking: ThinkingSetting | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EffectiveModelConfiguration(BaseModel):
    model_profile_id: str | None = None
    name: str | None = None
    provider: ProviderKind
    model: str
    base_url: str | None = None
    timeout_seconds: int = Field(ge=1)
    thinking: ThinkingSetting | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RepositoryInput(BaseModel):
    name: str
    path: Path | None = None
    url: str | None = None
    ref: str = "HEAD"
    since: str | None = "30 days ago"
    until: str | None = None
    branches: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    max_commits: int | None = Field(default=None, ge=1)

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().removesuffix(".git")


class DocumentationInput(BaseModel):
    name: str
    path: Path | None = None
    description: str | None = None
    content: str | None = None


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


class FileChange(BaseModel):
    file: str
    added: int | None = None
    removed: int | None = None


class DiffHint(BaseModel):
    file: str
    hint: str


class CommitEvidence(BaseModel):
    repo: str
    sha: str
    short_sha: str
    date: str
    subject: str
    body: str = ""
    files: list[str] = Field(default_factory=list)
    file_stats: list[FileChange] = Field(default_factory=list)
    diff_hints: list[DiffHint] = Field(default_factory=list)
    user_facing_score: int = 0


class DocumentationEvidence(BaseModel):
    name: str
    path: str
    excerpt: str


class BrowserScreenshotEvidence(BaseModel):
    scenario: str
    url: str
    path: str
    notes: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EvidenceBundle(BaseModel):
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    repositories: list[str] = Field(default_factory=list)
    commits: list[CommitEvidence] = Field(default_factory=list)
    documentation: list[DocumentationEvidence] = Field(default_factory=list)
    browser_screenshots: list[BrowserScreenshotEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EvidenceReference(BaseModel):
    source: str
    detail: str
    relevance: str


class ReviewerCheck(BaseModel):
    name: str
    status: str
    notes: str


class DocumentationUpdate(BaseModel):
    title: str
    summary: str
    user_facing_change: str
    proposed_update_markdown: str
    evidence_used: list[EvidenceReference]
    reviewer_checks: list[ReviewerCheck]
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
    artifacts: dict[str, str] = Field(default_factory=dict)


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
    mode: RunMode = RunMode.DEFAULT_BRANCH_PERIOD
    goal: str
    since: str | None = None
    until: str | None = None
    branches: dict[str, list[str]] = Field(default_factory=dict)
    provider: ProviderConfig | None = None
    audience: Audience | None = None
    task_interface_url: str | None = None
    screenshot_policy: ScreenshotPolicy = ScreenshotPolicy.DISABLED
    requested_model_settings: RequestedModelSettings | None = None
    project_profile_snapshot_id: str | None = None


class KnowledgeIndexStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class KnowledgeIndexRequest(BaseModel):
    project_id: str | None = None
    repositories: list[RepositoryInput] = Field(default_factory=list)
    documentation: list[DocumentationInput] = Field(default_factory=list)
    max_files: int = Field(default=500, ge=1, le=10_000)
    max_file_bytes: int = Field(default=200_000, ge=1, le=2_000_000)


class ProjectKnowledgeIndexRequest(BaseModel):
    max_files: int = Field(default=500, ge=1, le=10_000)
    max_file_bytes: int = Field(default=200_000, ge=1, le=2_000_000)


class KnowledgeIndexSummary(BaseModel):
    repositories: int = 0
    files: int = 0
    documentation_sources: int = 0
    nodes: int = 0
    edges: int = 0
    chunks: int = 0
    warnings: list[str] = Field(default_factory=list)


class KnowledgeIndexRun(BaseModel):
    id: str = Field(default_factory=lambda: f"kg-run-{uuid4().hex[:10]}")
    project_id: str | None = None
    status: KnowledgeIndexStatus = KnowledgeIndexStatus.QUEUED
    source_ref: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    request: KnowledgeIndexRequest
    summary: KnowledgeIndexSummary = Field(default_factory=KnowledgeIndexSummary)


class KnowledgeNode(BaseModel):
    id: str
    project_id: str | None = None
    repo: str | None = None
    kind: str
    name: str
    qualified_name: str
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    summary: str = ""
    content_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeEdge(BaseModel):
    id: str
    project_id: str | None = None
    source_node_id: str
    target_node_id: str
    edge_type: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeChunk(BaseModel):
    id: str
    project_id: str | None = None
    node_id: str
    repo: str | None = None
    path: str | None = None
    heading: str | None = None
    text: str
    token_count: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeGraphSnapshot(BaseModel):
    run: KnowledgeIndexRun
    nodes: list[KnowledgeNode]
    edges: list[KnowledgeEdge]
    chunks: list[KnowledgeChunk]


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    project_id: str | None = None
    kinds: list[str] = Field(default_factory=list)
    path_prefixes: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=50)


class KnowledgeSearchResult(BaseModel):
    node: KnowledgeNode
    chunk: KnowledgeChunk | None = None
    score: float
    matched_text: str


class KnowledgeContextPackRequest(BaseModel):
    goal: str = Field(min_length=1)
    project_id: str | None = None
    kinds: list[str] = Field(default_factory=list)
    path_prefixes: list[str] = Field(default_factory=list)
    token_budget: int = Field(default=1_500, ge=200, le=20_000)
    limit: int = Field(default=8, ge=1, le=30)


class KnowledgeContextPack(BaseModel):
    goal: str
    results: list[KnowledgeSearchResult]
    nodes: list[KnowledgeNode]
    edges: list[KnowledgeEdge]
    warnings: list[str] = Field(default_factory=list)


class BenchmarkCase(BaseModel):
    id: str
    name: str
    request: GuideSyncRunRequest


class BenchmarkSuite(BaseModel):
    name: str
    providers: list[ProviderConfig]
    cases: list[BenchmarkCase]


class BenchmarkScore(BaseModel):
    factuality: int = Field(ge=0, le=3)
    evidence_use: int = Field(ge=0, le=3)
    documentation_usefulness: int = Field(ge=0, le=3)
    traceability: int = Field(ge=0, le=3)
    reviewer_effort: int = Field(ge=0, le=3)


class BenchmarkResult(BaseModel):
    suite: str
    case_id: str
    provider: str
    model: str
    run_id: str
    status: str
    score: BenchmarkScore
    findings: list[ValidationFinding] = Field(default_factory=list)
    latency_ms: int | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
