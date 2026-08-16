from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import OperationError
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


class ScreenshotRetryDisposition(StrEnum):
    NONE = "none"
    RETRY_CAPTURE = "retry_capture"
    UNAVAILABLE = "unavailable"


class ScreenshotReviewVerdict(StrEnum):
    SUPPORTED = "supported"
    SUPPORTED_WITH_NOTES = "supported_with_notes"
    RETRY_CAPTURE = "retry_capture"
    REJECT = "reject"


class ScreenshotTheme(StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class ScreenshotActionKind(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    WAIT_FOR = "wait_for"
    WAIT = "wait"


class ScreenshotLocatorKind(StrEnum):
    ROLE = "role"
    LABEL = "label"
    TEXT = "text"
    TEST_ID = "test_id"


class ScreenshotViewport(BaseModel):
    width: int = Field(default=1440, ge=320, le=2560)
    height: int = Field(default=1000, ge=320, le=2000)


class ScreenshotAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ScreenshotActionKind
    locator_kind: ScreenshotLocatorKind | None = None
    locator: str | None = None
    role_name: str | None = None
    route: str | None = None
    wait_ms: int | None = Field(default=None, ge=0, le=5_000)

    @model_validator(mode="after")
    def validate_action_target(self) -> ScreenshotAction:
        if self.kind is ScreenshotActionKind.NAVIGATE and not self.route:
            raise ValueError("navigate screenshot actions require a route")
        if self.kind is ScreenshotActionKind.WAIT and self.wait_ms is None:
            raise ValueError("wait screenshot actions require wait_ms")
        if self.kind in {ScreenshotActionKind.CLICK, ScreenshotActionKind.WAIT_FOR} and (
            self.locator_kind is None or not self.locator
        ):
            raise ValueError("semantic screenshot actions require locator_kind and locator")
        return self


class ScreenshotCropRecord(BaseModel):
    mode: str
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None


class ScreenshotMaskRecord(BaseModel):
    reason: str
    locator_kind: ScreenshotLocatorKind
    locator: str


class ScreenshotPolicyAudit(BaseModel):
    registry_id: str
    permission: str
    risk: str
    resource_scope: str
    decision: str
    timeout_ms: int
    output_limit_chars: int
    retry_policy: str


class ScreenshotPlanItem(BaseModel):
    id: str
    change_id: str
    claim_id: str
    claim: str
    route: str
    actions: list[ScreenshotAction] = Field(default_factory=list, max_length=8)
    expected_text: list[str] = Field(default_factory=list, max_length=8)
    rejected_text: list[str] = Field(default_factory=list, max_length=8)
    requested_state: str
    viewport: ScreenshotViewport = Field(default_factory=ScreenshotViewport)
    theme: ScreenshotTheme = ScreenshotTheme.LIGHT
    capture_target: str = "viewport"
    caption: str
    alt_text: str
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)
    max_attempts: int = Field(default=3, ge=1, le=3)
    timeout_ms: int = Field(default=15_000, ge=1_000, le=30_000)
    retry_intent: str = "Retry with a bounded semantic wait."


class ScreenshotPlan(BaseModel):
    schema_version: str = "1.0"
    policy: str
    allowed_origin: str | None = None
    locale: str
    items: list[ScreenshotPlanItem] = Field(default_factory=list, max_length=4)


class ScreenshotVisionResult(BaseModel):
    adapter: str
    text: str = ""
    review_verdict: ScreenshotReviewVerdict | None = None
    confidence: float | None = None
    page_summary: str = ""
    ui_state: str = ""
    mismatches: list[str] = Field(default_factory=list)
    retry_disposition: ScreenshotRetryDisposition = (
        ScreenshotRetryDisposition.RETRY_CAPTURE
    )
    warnings: list[str] = Field(default_factory=list)
    role: ModelRole | None = None
    provider: str | None = None
    model: str | None = None
    raw_output: dict[str, object] = Field(default_factory=dict)
    model_metadata: dict[str, object] = Field(default_factory=dict)


class ScreenshotValidationAttempt(BaseModel):
    attempt: int = 1
    status: ScreenshotValidationStatus
    review_verdict: ScreenshotReviewVerdict | None = None
    adapter: str = "deterministic"
    expected_text: list[str] = Field(default_factory=list)
    visible_text: str = ""
    ocr_text: str | None = None
    matched_text: list[str] = Field(default_factory=list)
    missing_text: list[str] = Field(default_factory=list)
    rejected_text: list[str] = Field(default_factory=list)
    matched_rejected_text: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    retry_recommended: bool = False
    retry_disposition: ScreenshotRetryDisposition = ScreenshotRetryDisposition.NONE
    model_role: ModelRole | None = None
    provider: str | None = None
    model: str | None = None
    vision_warnings: list[str] = Field(default_factory=list)
    vision_raw_output: dict[str, object] = Field(default_factory=dict)
    page_summary: str = ""
    ui_state: str = ""
    semantic_mismatches: list[str] = Field(default_factory=list)
    confidence: float | None = None
    model_metadata: dict[str, object] = Field(default_factory=dict)


class ScreenshotObservation(BaseModel):
    scenario: str
    url: str
    attempt: int = Field(default=1, ge=1)
    retry_of_capture_id: str | None = None
    title: str | None = None
    viewport: dict[str, int] = Field(default_factory=dict)
    visible_text: str = ""
    matched_text: list[str] = Field(default_factory=list)
    missing_text: list[str] = Field(default_factory=list)
    console_errors: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)
    page_errors: list[str] = Field(default_factory=list)
    failed_requests: list[str] = Field(default_factory=list)
    image_hash: str | None = None
    raw_image_hash: str | None = None
    prepared_image_hash: str | None = None
    blank: bool = False
    ocr_text: str | None = None
    validation_status: ScreenshotValidationStatus | None = None
    validation_reasons: list[str] = Field(default_factory=list)
    retry_disposition: ScreenshotRetryDisposition = ScreenshotRetryDisposition.NONE
    capture_id: str | None = None
    scenario_id: str | None = None
    plan_item_id: str | None = None
    change_id: str | None = None
    claim_id: str | None = None
    route: str | None = None
    theme: ScreenshotTheme = ScreenshotTheme.LIGHT
    requested_state: str = ""
    observed_state: str = ""
    rejected_text: list[str] = Field(default_factory=list)
    matched_rejected_text: list[str] = Field(default_factory=list)
    dom_snapshot: str = ""
    dom_hash: str | None = None
    aria_snapshot: str = ""
    aria_hash: str | None = None
    browser_identity: str | None = None
    build_identity: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    raw_path: str | None = None
    raw_artifact_name: str | None = None
    prepared_artifact_name: str | None = None
    crop: ScreenshotCropRecord | None = None
    masks: list[ScreenshotMaskRecord] = Field(default_factory=list)
    caption: str = ""
    alt_text: str = ""
    capture_target: str = "viewport"
    duration_ms: int | None = None
    page_summary: str = ""
    ui_state: str = ""
    semantic_mismatches: list[str] = Field(default_factory=list)
    review_verdict: ScreenshotReviewVerdict | None = None
    vision_confidence: float | None = None
    vision_warnings: list[str] = Field(default_factory=list)
    publication_approved: bool = False
    policy_audit: ScreenshotPolicyAudit | None = None
    plan_item: ScreenshotPlanItem | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BrowserScreenshotEvidence(ScreenshotObservation):
    path: str
    notes: str | None = None

    @classmethod
    def from_capture(
        cls,
        capture: ScreenshotCaptureResult,
        *,
        notes: str | None = None,
    ) -> BrowserScreenshotEvidence:
        payload = capture.model_dump(
            exclude={"validation_attempts"},
        )
        payload["notes"] = notes
        return cls.model_validate(payload)


class ScreenshotCaptureResult(ScreenshotObservation):
    path: str
    validation_attempts: list[ScreenshotValidationAttempt] = Field(default_factory=list)


class ScreenshotCaptureFailure(BaseModel):
    scenario: str
    url: str
    attempt: int = 1
    error: OperationError
    policy_audit: ScreenshotPolicyAudit | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


ScreenshotCaptureOutcome = ScreenshotCaptureResult | ScreenshotCaptureFailure


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
