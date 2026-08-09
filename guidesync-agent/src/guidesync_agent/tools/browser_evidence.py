from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    EvidenceBundle,
    OperationError,
    ScreenshotCaptureResult,
    ScreenshotPolicyAudit,
    ScreenshotTheme,
)
from guidesync_agent.services.stable_ids import stable_id
from guidesync_agent.settings import BrowserToolSettings
from guidesync_agent.tools.browser_models import (
    BrowserCaptureContext,
    BrowserCaptureDiagnostics,
    BrowserCaptureErrorCode,
    BrowserCaptureFailure,
)
from guidesync_agent.tools.browser_support import route_for_url
from guidesync_agent.tools.registry import (
    DEFAULT_TOOL_REGISTRY_ID,
    PYDANTIC_AI_TOOL_DEFINITIONS,
)


def browser_policy_audit(
    context: BrowserCaptureContext,
    *,
    decision: str = "allowed",
) -> ScreenshotPolicyAudit:
    return browser_policy_audit_from_config(context, decision)


def browser_policy_audit_from_config(
    config: BrowserToolSettings | BrowserCaptureContext,
    decision: str,
) -> ScreenshotPolicyAudit:
    definition = PYDANTIC_AI_TOOL_DEFINITIONS["capture_ui_screenshot"]
    return ScreenshotPolicyAudit(
        registry_id=DEFAULT_TOOL_REGISTRY_ID,
        permission=definition.permission.value,
        risk=definition.risk.value,
        resource_scope=definition.scope.value,
        decision=decision,
        timeout_ms=config.timeout_ms,
        output_limit_chars=definition.max_output_chars,
        retry_policy=definition.retry_policy,
    )


def text_hash(value: str) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def record_screenshot(
    context: BrowserCaptureContext,
    diagnostics: BrowserCaptureDiagnostics,
) -> BrowserScreenshotEvidence:
    image_hash = file_hash(context.path)
    raw_hash = file_hash(context.raw_path)
    blank = is_blank_screenshot(context.path)
    matched_text = [
        item
        for item in context.expected_text
        if item.lower() in diagnostics.visible_text.lower()
    ]
    missing_text = [item for item in context.expected_text if item not in matched_text]
    matched_rejected = [
        item
        for item in context.rejected_text
        if item.lower() in diagnostics.visible_text.lower()
    ]
    item = context.plan_item
    final_url = diagnostics.final_url or context.target_url
    screenshot = BrowserScreenshotEvidence(
        scenario=context.scenario,
        url=final_url,
        path=str(context.path),
        title=diagnostics.title,
        viewport=context.viewport,
        visible_text=diagnostics.visible_text,
        matched_text=matched_text,
        missing_text=missing_text,
        console_errors=diagnostics.console_errors,
        network_errors=diagnostics.network_errors,
        page_errors=diagnostics.page_errors,
        failed_requests=diagnostics.failed_requests,
        image_hash=image_hash,
        raw_image_hash=raw_hash,
        prepared_image_hash=image_hash,
        blank=blank,
        notes=diagnostics.notes,
        capture_id=stable_id("capture", context.scenario, final_url, str(context.path)),
        scenario_id=item.id if item else context.scenario,
        plan_item_id=item.id if item else None,
        change_id=item.change_id if item else None,
        claim_id=item.claim_id if item else None,
        route=route_for_url(final_url),
        theme=item.theme if item else ScreenshotTheme.LIGHT,
        requested_state=item.requested_state if item else "",
        observed_state=diagnostics.title or "",
        rejected_text=context.rejected_text,
        matched_rejected_text=matched_rejected,
        dom_snapshot=diagnostics.dom_snapshot,
        dom_hash=text_hash(diagnostics.dom_snapshot),
        aria_snapshot=diagnostics.aria_snapshot,
        aria_hash=text_hash(diagnostics.aria_snapshot),
        browser_identity=diagnostics.browser_identity,
        build_identity=diagnostics.build_identity,
        raw_path=str(context.raw_path),
        raw_artifact_name=context.raw_path.name,
        prepared_artifact_name=context.path.name,
        crop=diagnostics.crop,
        masks=diagnostics.masks,
        caption=item.caption if item else "",
        alt_text=item.alt_text if item else "",
        capture_target=item.capture_target if item else "viewport",
        duration_ms=diagnostics.duration_ms,
        policy_audit=browser_policy_audit(context),
        plan_item=item,
    )
    context.evidence.browser_screenshots.append(screenshot)
    return screenshot


def replace_evidence_capture(
    evidence: EvidenceBundle,
    capture: ScreenshotCaptureResult,
) -> None:
    screenshot = BrowserScreenshotEvidence.from_capture(
        capture,
        notes="Captured by the bounded release-notes browser tool.",
    )
    index = next(
        (
            item_index
            for item_index, item in enumerate(evidence.browser_screenshots)
            if item.path == capture.path or item.capture_id == capture.capture_id
        ),
        None,
    )
    if index is None:
        evidence.browser_screenshots.append(screenshot)
    else:
        evidence.browser_screenshots[index] = screenshot


def browser_capture_failure(
    code: BrowserCaptureErrorCode,
    message: str,
    *,
    retryable: bool = False,
    policy_audit: ScreenshotPolicyAudit | None = None,
) -> BrowserCaptureFailure:
    return BrowserCaptureFailure(
        error=OperationError(
            code=code.value,
            message=message,
            retryable=retryable,
        ),
        policy_audit=policy_audit,
    )


def dump_browser_capture(
    capture: BrowserScreenshotEvidence | BrowserCaptureFailure,
) -> dict[str, Any]:
    return capture.model_dump(mode="json")


def file_hash(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def is_blank_screenshot(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return True
    if not data:
        return True
    return len(set(data[:4096])) <= 2 and len(data) < 4096
