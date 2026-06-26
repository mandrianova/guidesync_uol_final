from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


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
