from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .model_roles import ModelRole


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


class ScreenshotValidationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    RETRY = "retry"
    SKIPPED = "skipped"


class ScreenshotVisionResult(BaseModel):
    adapter: str
    text: str = ""
    confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    role: ModelRole | None = None
    provider: str | None = None
    model: str | None = None
    raw_output: dict[str, object] = Field(default_factory=dict)
    model_metadata: dict[str, object] = Field(default_factory=dict)


class ScreenshotValidationAttempt(BaseModel):
    attempt: int = 1
    status: ScreenshotValidationStatus
    adapter: str = "deterministic"
    expected_text: list[str] = Field(default_factory=list)
    visible_text: str = ""
    ocr_text: str | None = None
    matched_text: list[str] = Field(default_factory=list)
    missing_text: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    retry_recommended: bool = False
    model_role: ModelRole | None = None
    provider: str | None = None
    model: str | None = None
    vision_warnings: list[str] = Field(default_factory=list)
    vision_raw_output: dict[str, object] = Field(default_factory=dict)
    model_metadata: dict[str, object] = Field(default_factory=dict)


class BrowserScreenshotEvidence(BaseModel):
    scenario: str
    url: str
    path: str
    title: str | None = None
    viewport: dict[str, int] = Field(default_factory=dict)
    visible_text: str = ""
    matched_text: list[str] = Field(default_factory=list)
    missing_text: list[str] = Field(default_factory=list)
    console_errors: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)
    image_hash: str | None = None
    blank: bool = False
    ocr_text: str | None = None
    validation_status: ScreenshotValidationStatus | None = None
    validation_reasons: list[str] = Field(default_factory=list)
    attempts: int = 1
    notes: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ScreenshotCaptureResult(BaseModel):
    ok: bool = True
    scenario: str
    url: str
    attempt: int = 1
    path: str | None = None
    title: str | None = None
    viewport: dict[str, int] = Field(default_factory=dict)
    visible_text: str = ""
    matched_text: list[str] = Field(default_factory=list)
    missing_text: list[str] = Field(default_factory=list)
    console_errors: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)
    image_hash: str | None = None
    blank: bool = False
    ocr_text: str | None = None
    validation_status: ScreenshotValidationStatus | None = None
    validation_reasons: list[str] = Field(default_factory=list)
    validation_attempts: list[ScreenshotValidationAttempt] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectProfileContextEvidence(BaseModel):
    id: str
    version: int
    prompt_version: str
    summary: str = ""
    project_description: str = ""
    project_structure: list[str] = Field(default_factory=list)
    architecture: list[str] = Field(default_factory=list)
    core_concepts: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
    agent_context: str = ""
    taxonomy_version: str | None = None
    categories: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    documentation_areas: list[str] = Field(default_factory=list)
    domain_terms: list[str] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    repositories: list[str] = Field(default_factory=list)
    project_profile: ProjectProfileContextEvidence | None = None
    commits: list[CommitEvidence] = Field(default_factory=list)
    documentation: list[DocumentationEvidence] = Field(default_factory=list)
    browser_screenshots: list[BrowserScreenshotEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EvidenceReference(BaseModel):
    source: str
    detail: str
    relevance: str
