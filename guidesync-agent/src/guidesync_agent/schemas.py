from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class ProviderKind(StrEnum):
    MOCK = "mock"
    PYDANTIC_AI = "pydantic_ai"
    LOCAL_HTTP = "local_http"


class RunMode(StrEnum):
    DEFAULT_BRANCH_PERIOD = "default_branch_period"
    SELECT_BRANCHES = "select_branches"


class ProviderConfig(BaseModel):
    provider: ProviderKind = ProviderKind.MOCK
    model: str = "mock:deterministic"
    name: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    api_key: str | None = Field(default=None, exclude=True)
    timeout_seconds: int = Field(default=60, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelSettings(BaseModel):
    provider: ProviderKind = ProviderKind.LOCAL_HTTP
    model: str = "google/gemma-4-31b-qat"
    base_url: str | None = "http://localhost:1234/api/v1/chat"
    api_key: str | None = Field(default=None, exclude=True)
    has_api_key: bool = False
    timeout_seconds: int = Field(default=60, ge=1)


class ModelSettingsUpdate(BaseModel):
    provider: ProviderKind
    model: str
    base_url: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    timeout_seconds: int = Field(default=60, ge=1)


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
    title: str = "GuideSync documentation update"
    formats: list[str] = Field(default_factory=lambda: ["html", "md", "json"])


class GuideSyncRunRequest(BaseModel):
    run_id: str = Field(default_factory=lambda: f"run-{uuid4().hex[:10]}")
    goal: str
    audience: str = "documentation reviewer"
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    repositories: list[RepositoryInput] = Field(default_factory=list)
    documentation: list[DocumentationInput] = Field(default_factory=list)
    report: ReportConfig = Field(default_factory=ReportConfig)
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


class EvidenceBundle(BaseModel):
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    repositories: list[str] = Field(default_factory=list)
    commits: list[CommitEvidence] = Field(default_factory=list)
    documentation: list[DocumentationEvidence] = Field(default_factory=list)
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
    id: str = Field(default_factory=lambda: f"repo-{uuid4().hex[:10]}")
    name: str
    url: str
    default_branch: str | None = None
    paths: list[str] = Field(default_factory=list)


class ProjectDocumentation(BaseModel):
    id: str = Field(default_factory=lambda: f"doc-{uuid4().hex[:10]}")
    name: str
    description: str | None = None
    content: str = ""


class ProjectConfig(BaseModel):
    id: str = Field(default_factory=lambda: f"project-{uuid4().hex[:10]}")
    name: str
    description: str | None = None
    repositories: list[ProjectRepository] = Field(default_factory=list)
    documentation: list[ProjectDocumentation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    repositories: list[ProjectRepository] = Field(default_factory=list)
    documentation: list[ProjectDocumentation] = Field(default_factory=list)


class ProjectRunRequest(BaseModel):
    mode: RunMode = RunMode.DEFAULT_BRANCH_PERIOD
    goal: str
    since: str | None = None
    until: str | None = None
    branches: dict[str, list[str]] = Field(default_factory=dict)
    provider: ProviderConfig | None = None
    audience: str = "documentation reviewer"


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
