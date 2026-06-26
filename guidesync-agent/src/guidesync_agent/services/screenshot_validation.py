from __future__ import annotations

from typing import Protocol

from guidesync_agent.schemas import (
    ScreenshotCaptureResult,
    ScreenshotValidationAttempt,
    ScreenshotValidationStatus,
    ScreenshotVisionResult,
)


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


def validate_screenshot_capture(
    capture: ScreenshotCaptureResult,
    expected_text: list[str],
    *,
    adapter: ScreenshotVisionAdapter | None = None,
) -> ScreenshotValidationAttempt:
    adapter = adapter or DeterministicScreenshotVisionAdapter()
    vision = adapter.extract_text(capture)
    visible_text = capture.visible_text or ""
    ocr_text = vision.text or capture.ocr_text
    combined_text = " ".join([visible_text, ocr_text or ""])
    matched_text, missing_text = match_expected_text(expected_text, combined_text)
    _, ocr_missing_text = match_expected_text(expected_text, ocr_text or "")
    reasons: list[str] = []

    if not capture.ok:
        reasons.append("capture_failed")
    if capture.blank or low_information_text(combined_text):
        reasons.append("blank_or_low_information_image")
    if missing_text:
        reasons.append("missing_expected_text")
    if ocr_text is not None and expected_text and ocr_missing_text:
        reasons.append("ocr_missing_expected_text")

    retry_recommended = any(
        reason in reasons
        for reason in {
            "capture_failed",
            "blank_or_low_information_image",
            "missing_expected_text",
        }
    )
    if retry_recommended:
        status = ScreenshotValidationStatus.RETRY
    elif reasons:
        status = ScreenshotValidationStatus.FAILED
    else:
        status = ScreenshotValidationStatus.PASSED

    return ScreenshotValidationAttempt(
        attempt=capture.attempt,
        status=status,
        adapter=vision.adapter,
        expected_text=expected_text,
        visible_text=visible_text,
        ocr_text=ocr_text,
        matched_text=matched_text,
        missing_text=missing_text or ocr_missing_text,
        reasons=reasons,
        retry_recommended=retry_recommended,
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
    return capture.model_copy(
        update={
            "matched_text": final.matched_text,
            "missing_text": final.missing_text,
            "ocr_text": final.ocr_text,
            "validation_status": terminal_status,
            "validation_reasons": final.reasons,
            "validation_attempts": attempts,
        }
    )


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
