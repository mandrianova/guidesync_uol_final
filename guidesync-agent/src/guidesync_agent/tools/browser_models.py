from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr

from guidesync_agent.schemas import (
    EvidenceBundle,
    OperationError,
    ScreenshotCropRecord,
    ScreenshotMaskRecord,
    ScreenshotPlanItem,
    ScreenshotPolicyAudit,
    ScreenshotRetryDisposition,
    ScreenshotReviewVerdict,
    ScreenshotValidationStatus,
    TaskInterfaceAuthType,
)


class BrowserCaptureErrorCode(StrEnum):
    DISABLED = "browser_disabled"
    URL_REQUIRED = "browser_url_required"
    PLAYWRIGHT_UNAVAILABLE = "playwright_unavailable"
    BROWSER_UNAVAILABLE = "browser_unavailable"
    CAPTURE_FAILED = "browser_capture_failed"
    PROCESS_FAILED = "browser_process_failed"
    ORIGIN_DENIED = "browser_origin_denied"
    INVALID_ACTION = "browser_invalid_action"


class BrowserCaptureFailure(BaseModel):
    error: OperationError
    policy_audit: ScreenshotPolicyAudit | None = None


class ScreenshotCaptureToolResult(BaseModel):
    status: str = "captured"
    capture_id: str | None = None
    scenario_id: str
    change_id: str
    attempt: int = 1
    retry_of_capture_id: str | None = None
    validation_status: ScreenshotValidationStatus
    review_verdict: ScreenshotReviewVerdict | None = None
    retry_disposition: ScreenshotRetryDisposition
    retry_recommended: bool
    validation_reasons: list[str] = Field(default_factory=list, max_length=8)
    matched_text: list[str] = Field(default_factory=list, max_length=8)
    missing_text: list[str] = Field(default_factory=list, max_length=8)
    semantic_mismatches: list[str] = Field(default_factory=list, max_length=4)
    requested_state: str = Field(max_length=1_000)
    observed_state: str = Field(max_length=1_000)
    next_action: str = Field(max_length=600)


@dataclass(frozen=True)
class BrowserScreenshotRequest:
    scenario: str
    url: str | None = None
    steps: list[str] = field(default_factory=list)
    width: int = 1440
    height: int = 1000
    expected_text: list[str] = field(default_factory=list)
    rejected_text: list[str] = field(default_factory=list)
    attempt: int = 1
    retry_of_capture_id: str | None = None
    plan_item: ScreenshotPlanItem | None = None


@dataclass(frozen=True)
class BrowserCaptureContext:
    evidence: EvidenceBundle
    scenario: str
    target_url: str
    path: Path
    steps: list[str]
    width: int
    height: int
    timeout_ms: int
    expected_text: list[str]
    rejected_text: list[str] = field(default_factory=list)
    attempt: int = 1
    retry_of_capture_id: str | None = None
    plan_item: ScreenshotPlanItem | None = None
    browser_binary: Path | None = None
    auth_type: TaskInterfaceAuthType | None = None
    auth_secret: SecretStr | None = field(default=None, repr=False)

    @property
    def viewport(self) -> dict[str, int]:
        return {"width": self.width, "height": self.height}

    @property
    def raw_path(self) -> Path:
        return self.path.with_name(f"{self.path.stem}-raw{self.path.suffix}")


@dataclass(frozen=True)
class BrowserCaptureDiagnostics:
    notes: str
    title: str | None = None
    visible_text: str = ""
    console_errors: list[str] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    final_url: str | None = None
    dom_snapshot: str = ""
    aria_snapshot: str = ""
    browser_identity: str | None = None
    build_identity: str | None = None
    duration_ms: int | None = None
    crop: ScreenshotCropRecord | None = None
    masks: list[ScreenshotMaskRecord] = field(default_factory=list)


@dataclass(frozen=True)
class BrowserPreparedImage:
    crop: ScreenshotCropRecord
    masks: list[ScreenshotMaskRecord] = field(default_factory=list)


@dataclass
class BrowserCaptureEvents:
    console_errors: list[str] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
