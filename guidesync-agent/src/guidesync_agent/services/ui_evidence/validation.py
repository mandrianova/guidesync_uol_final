from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import struct
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field
from pydantic_ai.messages import BinaryImage, TextContent, UserContent

from guidesync_agent.agent_runtime.concurrency import agent_concurrency_key
from guidesync_agent.agent_runtime.model_usage import (
    endpoint_host_hash,
    sanitized_model_metadata,
)
from guidesync_agent.agent_runtime.pydantic_ai import (
    PydanticAgentRunRequest,
    run_pydantic_agent_sync,
)
from guidesync_agent.prompts.screenshot_vision import screenshot_vision_prompt_file
from guidesync_agent.schemas import (
    ModelRole,
    ReportLocale,
    ScreenshotCaptureFailure,
    ScreenshotCaptureResult,
    ScreenshotCropRecord,
    ScreenshotRetryDisposition,
    ScreenshotReviewVerdict,
    ScreenshotValidationAttempt,
    ScreenshotValidationStatus,
    ScreenshotVisionResult,
)
from guidesync_agent.services.model_roles import provider_config_for_role
from guidesync_agent.settings import get_settings

UNAVAILABLE_CONFIDENCE_THRESHOLD = 0.8


class ScreenshotVisionAdapter(Protocol):
    name: str

    def extract_text(self, capture: ScreenshotCaptureResult) -> ScreenshotVisionResult: ...


class DeterministicScreenshotVisionAdapter:
    name = "deterministic"

    def extract_text(self, capture: ScreenshotCaptureResult) -> ScreenshotVisionResult:
        return ScreenshotVisionResult(
            adapter=self.name,
            text=capture.ocr_text or capture.visible_text,
        )


class ScreenshotVisionModelOutput(BaseModel):
    visible_text: str = ""
    page_summary: str = ""
    ui_state: str = ""
    review_verdict: ScreenshotReviewVerdict
    mismatches: list[str] = Field(default_factory=list)
    retry_disposition: ScreenshotRetryDisposition = (
        ScreenshotRetryDisposition.RETRY_CAPTURE
    )
    confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)


class ModelBackedScreenshotVisionAdapter:
    name = "model_backed_screenshot_vision"

    def __init__(
        self,
        *,
        project_id: str | None = None,
        run_id: str | None = None,
        workflow_task_id: str | None = None,
        held_model_concurrency_key: str | None = None,
    ) -> None:
        self.config = provider_config_for_role(ModelRole.SCREENSHOT_VISION)
        self.project_id = project_id
        self.run_id = run_id
        self.workflow_task_id = workflow_task_id
        self.acquire_concurrency_slot = (
            held_model_concurrency_key is None
            or held_model_concurrency_key != agent_concurrency_key(self.config)
        )

    def extract_text(self, capture: ScreenshotCaptureResult) -> ScreenshotVisionResult:
        metadata = sanitized_model_metadata(
            {
                **self.config.metadata,
                "model_role": ModelRole.SCREENSHOT_VISION.value,
                "provider": self.config.provider.value,
                "model": self.config.model,
                "base_url_host_hash": endpoint_host_hash(self.config.base_url),
            }
        )
        if not self.config.base_url:
            return self.failed_result("Screenshot vision requires a base URL.", metadata)
        if not capture.path:
            return self.failed_result("Screenshot capture did not produce an image path.", metadata)
        path = Path(capture.path)
        if not path.exists():
            return self.failed_result(f"Screenshot file does not exist: {path}", metadata)
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        try:
            prompt = screenshot_vision_user_content(path, capture)
            prompt_file = screenshot_vision_prompt_file()
            runtime_result = run_pydantic_agent_sync(
                PydanticAgentRunRequest(
                    prompt=prompt,
                    instructions=prompt_file.content,
                    output_model=ScreenshotVisionModelOutput,
                    deps=None,
                    deps_type=type(None),
                    config=self.config,
                    model_role=ModelRole.SCREENSHOT_VISION,
                    project_id=self.project_id,
                    run_id=self.run_id,
                    workflow_task_id=self.workflow_task_id,
                    prompt_metadata=prompt_file.usage_metadata("screenshot_vision"),
                    retries=2,
                    requires_tools=False,
                    acquire_concurrency_slot=self.acquire_concurrency_slot,
                )
            )
            completed_at = datetime.now(UTC)
            output = ScreenshotVisionModelOutput.model_validate(runtime_result.output)
            raw = output.model_dump(mode="json")
            text = output.visible_text or capture.ocr_text or capture.visible_text
            model_metadata = {
                **metadata,
                **runtime_result.usage,
                "model_call_attempted": True,
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "image_input_units": 1,
                "prompt_input_chars": len(screenshot_vision_prompt(capture)),
            }
            return ScreenshotVisionResult(
                adapter=self.name,
                text=text,
                review_verdict=output.review_verdict,
                confidence=output.confidence,
                page_summary=output.page_summary,
                ui_state=output.ui_state,
                mismatches=output.mismatches,
                retry_disposition=output.retry_disposition,
                warnings=output.warnings,
                role=ModelRole.SCREENSHOT_VISION,
                provider=self.config.provider.value,
                model=self.config.model,
                raw_output=raw,
                model_metadata=model_metadata,
            )
        except Exception as exc:  # noqa: BLE001 - validation should record provider errors
            completed_at = datetime.now(UTC)
            warning = f"Screenshot vision request failed: {exc}"
            return self.failed_result(
                warning,
                {
                    **metadata,
                    "model_call_attempted": True,
                    "started_at": started_at.isoformat(),
                    "completed_at": completed_at.isoformat(),
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "image_input_units": 1,
                    "prompt_input_chars": len(screenshot_vision_prompt(capture)),
                    "error": warning,
                },
            )

    def failed_result(self, warning: str, metadata: dict[str, object]) -> ScreenshotVisionResult:
        return ScreenshotVisionResult(
            adapter=self.name,
            warnings=[warning],
            role=ModelRole.SCREENSHOT_VISION,
            provider=self.config.provider.value,
            model=self.config.model,
            model_metadata=metadata,
        )


def default_screenshot_vision_adapter(
    *,
    project_id: str | None = None,
    run_id: str | None = None,
    workflow_task_id: str | None = None,
    held_model_concurrency_key: str | None = None,
) -> ScreenshotVisionAdapter:
    configured = (get_settings().models.screenshot_vision.provider or "").strip().lower()
    if configured in {"deterministic", "deterministic_test", "fake", "fixture"}:
        return DeterministicScreenshotVisionAdapter()
    return ModelBackedScreenshotVisionAdapter(
        project_id=project_id,
        run_id=run_id,
        workflow_task_id=workflow_task_id,
        held_model_concurrency_key=held_model_concurrency_key,
    )


def validate_screenshot_capture(
    capture: ScreenshotCaptureResult,
    expected_text: list[str],
    *,
    rejected_text: list[str] | None = None,
    locale: ReportLocale = ReportLocale.ENGLISH,
    adapter: ScreenshotVisionAdapter | None = None,
) -> ScreenshotValidationAttempt:
    adapter = adapter or default_screenshot_vision_adapter()
    vision = adapter.extract_text(capture)
    visible_text = capture.visible_text or ""
    ocr_text = vision.text or capture.ocr_text
    combined_parts = [visible_text]
    if ocr_text and ocr_text != visible_text:
        combined_parts.append(ocr_text)
    combined_text = " ".join(combined_parts)
    matched_text, missing_text = match_expected_text(expected_text, combined_text)
    _, ocr_missing_text = match_expected_text(expected_text, ocr_text or "")
    rejected_text = rejected_text or []
    matched_rejected, _ = match_expected_text(rejected_text, combined_text)
    reasons = screenshot_validation_reasons(
        capture,
        combined_text,
        target_relevant_text(combined_text, expected_text),
        missing_text,
        ocr_missing_text if ocr_text is not None and expected_text else [],
        matched_rejected,
        locale,
        vision,
    )

    status, retry_disposition = screenshot_validation_outcome(reasons, vision)
    retry_recommended = (
        retry_disposition is ScreenshotRetryDisposition.RETRY_CAPTURE
    )

    return ScreenshotValidationAttempt(
        attempt=capture.attempt,
        status=status,
        review_verdict=vision.review_verdict,
        adapter=vision.adapter,
        expected_text=expected_text,
        visible_text=visible_text,
        ocr_text=ocr_text,
        matched_text=matched_text,
        missing_text=missing_text or ocr_missing_text,
        rejected_text=rejected_text,
        matched_rejected_text=matched_rejected,
        reasons=reasons,
        retry_recommended=retry_recommended,
        retry_disposition=retry_disposition,
        model_role=vision.role,
        provider=vision.provider,
        model=vision.model,
        vision_warnings=vision.warnings,
        vision_raw_output=vision.raw_output,
        page_summary=vision.page_summary,
        ui_state=vision.ui_state,
        semantic_mismatches=vision.mismatches,
        confidence=vision.confidence,
        model_metadata=vision.model_metadata,
    )


def validate_screenshot_capture_failure(
    capture: ScreenshotCaptureFailure,
) -> ScreenshotValidationAttempt:
    return ScreenshotValidationAttempt(
        attempt=capture.attempt,
        status=ScreenshotValidationStatus.RETRY,
        reasons=["capture_failed"],
        retry_recommended=True,
        retry_disposition=ScreenshotRetryDisposition.RETRY_CAPTURE,
    )


def finalize_screenshot_capture(
    capture: ScreenshotCaptureResult,
    attempts: list[ScreenshotValidationAttempt],
) -> ScreenshotCaptureResult:
    final = attempts[-1]
    terminal_status = (
        ScreenshotValidationStatus.FAILED
        if final.status == ScreenshotValidationStatus.RETRY
        else final.status
    )
    finalized = capture.model_copy(
        update={
            "matched_text": final.matched_text,
            "missing_text": final.missing_text,
            "ocr_text": final.ocr_text,
            "validation_status": terminal_status,
            "validation_reasons": final.reasons,
            "retry_disposition": final.retry_disposition,
            "validation_attempts": attempts,
            "matched_rejected_text": final.matched_rejected_text,
            "page_summary": final.page_summary,
            "ui_state": final.ui_state,
            "semantic_mismatches": final.semantic_mismatches,
            "review_verdict": final.review_verdict,
            "vision_confidence": final.confidence,
            "vision_warnings": final.vision_warnings,
            "observed_state": final.ui_state or final.page_summary or capture.title or "",
        }
    )
    return prepare_publication_capture(finalized)


def match_expected_text(expected_text: list[str], text: str) -> tuple[list[str], list[str]]:
    normalized = text.lower()
    matched: list[str] = []
    missing: list[str] = []
    for item in expected_text:
        expected = item.strip().lower()
        if not expected:
            continue
        if expected in normalized:
            matched.append(item)
        else:
            missing.append(item)
    return matched, missing


def low_information_text(text: str) -> bool:
    return len(text.strip()) < 3


def screenshot_validation_reasons(  # noqa: PLR0913 - validation inputs are orthogonal
    capture: ScreenshotCaptureResult,
    combined_text: str,
    language_text: str,
    missing_text: list[str],
    ocr_missing_text: list[str],
    matched_rejected: list[str],
    locale: ReportLocale,
    vision: ScreenshotVisionResult,
) -> list[str]:
    reasons = page_state_reasons(
        combined_text,
        capture.title or "",
        locale,
        language_text=language_text,
    )
    checks = (
        (capture.blank or low_information_text(combined_text), "blank_or_low_information_image"),
        (bool(missing_text), "missing_expected_text"),
        (bool(ocr_missing_text), "ocr_missing_expected_text"),
        (bool(matched_rejected), "rejected_state_visible"),
        (bool(vision.mismatches), "semantic_mismatch"),
        (vision.confidence is not None and vision.confidence < 0.5, "low_semantic_confidence"),
        (bool(vision.warnings) and vision.review_verdict is None, "vision_review_failed"),
    )
    reasons.extend(reason for present, reason in checks if present)
    return list(dict.fromkeys(reasons))


def screenshot_validation_outcome(
    reasons: list[str],
    vision: ScreenshotVisionResult,
) -> tuple[ScreenshotValidationStatus, ScreenshotRetryDisposition]:
    hard_blockers = {
        "blank_or_low_information_image",
        "auth_page",
        "error_page",
        "loading_only_state",
        "rejected_state_visible",
        "privacy_sensitive_content",
    }
    if hard_blockers.intersection(reasons):
        outcome = (
            ScreenshotValidationStatus.RETRY,
            ScreenshotRetryDisposition.RETRY_CAPTURE,
        )
    elif vision.review_verdict in {
        ScreenshotReviewVerdict.SUPPORTED,
        ScreenshotReviewVerdict.SUPPORTED_WITH_NOTES,
    }:
        outcome = ScreenshotValidationStatus.PASSED, ScreenshotRetryDisposition.NONE
    elif vision.review_verdict is ScreenshotReviewVerdict.RETRY_CAPTURE:
        outcome = (
            ScreenshotValidationStatus.RETRY,
            ScreenshotRetryDisposition.RETRY_CAPTURE,
        )
    elif vision.review_verdict is ScreenshotReviewVerdict.REJECT:
        outcome = ScreenshotValidationStatus.FAILED, ScreenshotRetryDisposition.UNAVAILABLE
    # Deterministic and legacy adapters do not produce semantic verdicts. Preserve
    # their conservative validation behaviour.
    elif not reasons:
        outcome = ScreenshotValidationStatus.PASSED, ScreenshotRetryDisposition.NONE
    elif (
        vision.retry_disposition is ScreenshotRetryDisposition.UNAVAILABLE
        and vision.confidence is not None
        and vision.confidence >= UNAVAILABLE_CONFIDENCE_THRESHOLD
    ):
        outcome = ScreenshotValidationStatus.FAILED, ScreenshotRetryDisposition.UNAVAILABLE
    else:
        outcome = ScreenshotValidationStatus.RETRY, ScreenshotRetryDisposition.RETRY_CAPTURE
    return outcome


def target_relevant_text(
    text: str,
    expected_text: list[str],
    *,
    leading_context: int = 40,
    trailing_context: int = 240,
) -> str:
    normalized = text.casefold()
    snippets: list[str] = []
    for expected in expected_text:
        needle = expected.strip().casefold()
        if not needle:
            continue
        start = normalized.find(needle)
        if start < 0:
            continue
        snippets.append(
            text[
                max(0, start - leading_context) : min(
                    len(text),
                    start + len(needle) + trailing_context,
                )
            ]
        )
    return " ".join(snippets) if snippets else text


def page_state_reasons(
    text: str,
    title: str,
    locale: ReportLocale,
    *,
    language_text: str | None = None,
) -> list[str]:
    normalized = f"{title} {text}".casefold()
    normalized_text = text.strip().casefold()
    reasons = []
    if any(value in normalized for value in ("404", "not found", "server error")):
        reasons.append("error_page")
    if any(
        value in normalized
        for value in ("sign in", "log in", "login", "forgot password", "remember me")
    ):
        reasons.append("auth_page")
    if normalized_text in {"loading", "loading…", "loading..."}:
        reasons.append("loading_only_state")
    if wrong_language(language_text if language_text is not None else text, locale):
        reasons.append("wrong_language")
    if contains_private_data(text):
        reasons.append("privacy_sensitive_content")
    return reasons


def wrong_language(text: str, locale: ReportLocale) -> bool:
    letters = [character for character in text if character.isalpha()]
    if len(letters) < 20:
        return False
    cyrillic = sum(
        "\u0430" <= character.casefold() <= "\u044f" or character.casefold() == "\u0451"
        for character in letters
    )
    ratio = cyrillic / len(letters)
    return ratio < 0.5 if locale is ReportLocale.RUSSIAN else ratio >= 0.5


def contains_private_data(text: str) -> bool:
    patterns = (
        r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
        r"\b(?:bearer|api[_ -]?key|token|password)\s*[:=]\s*\S+",
        r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b",
        r"https?://(?:localhost|127\.0\.0\.1|host\.docker\.internal|[^\s/]+\.internal)\S*",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def prepare_publication_capture(capture: ScreenshotCaptureResult) -> ScreenshotCaptureResult:
    source = Path(capture.path)
    raw_path = Path(capture.raw_path) if capture.raw_path else source
    raw_hash = hash_file(raw_path)
    if capture.validation_status is not ScreenshotValidationStatus.PASSED:
        return capture.model_copy(
            update={
                "raw_path": str(raw_path),
                "raw_artifact_name": raw_path.name,
                "raw_image_hash": raw_hash,
                "publication_approved": False,
            }
        )

    prepared = source
    if source == raw_path:
        prepared = source.with_name(f"{source.stem}-prepared{source.suffix}")
        shutil.copyfile(source, prepared)
    width, height = image_dimensions(prepared, capture.viewport)
    prepared_hash = hash_file(prepared)
    return capture.model_copy(
        update={
            "path": str(prepared),
            "raw_path": str(raw_path),
            "raw_artifact_name": raw_path.name,
            "prepared_artifact_name": prepared.name,
            "raw_image_hash": raw_hash,
            "prepared_image_hash": prepared_hash,
            "image_hash": prepared_hash,
            "image_width": width,
            "image_height": height,
            "crop": capture.crop
            or ScreenshotCropRecord(
                mode="viewport",
                width=float(width),
                height=float(height),
            ),
            "publication_approved": True,
        }
    )


def image_dimensions(path: Path, viewport: dict[str, int]) -> tuple[int, int]:
    try:
        header = path.read_bytes()[:24]
    except OSError:
        header = b""
    if len(header) == 24 and header[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", header[16:24])
    return viewport.get("width", 1440), viewport.get("height", 1000)


def hash_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def screenshot_vision_user_content(
    path: Path,
    capture: ScreenshotCaptureResult,
) -> list[UserContent]:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return [
        TextContent(screenshot_vision_prompt(capture)),
        BinaryImage(path.read_bytes(), media_type=mime),
    ]


def screenshot_vision_prompt(capture: ScreenshotCaptureResult) -> str:
    prompt = [
        "Extract visible UI text, summarize the screen state, and assess whether the "
        "image materially supports the primary evidence claim. Return only JSON matching "
        "the schema, including review_verdict. Put unsupported, cropped, or contradictory "
        "details in mismatches without rejecting an otherwise supported primary claim. "
        "Generic page presence is not sufficient evidence."
    ]
    if item := capture.plan_item:
        prompt.extend(
            [
                f"Evidence claim: {item.claim}",
                f"Requested state: {item.requested_state}",
                f"Intended caption: {item.caption}",
                f"Intended alt text: {item.alt_text}",
                f"Capture target: {item.capture_target}",
            ]
        )
    if capture.visible_text:
        prompt.extend(["Browser-visible text hint:", capture.visible_text])
    return "\n".join(prompt)
