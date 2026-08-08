from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guidesync_agent.agent_runtime.screenshot_model_usage import (
    ScreenshotModelUsageContext,
    record_screenshot_model_usage,
)
from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    EvidenceBundle,
    FileChangeSummary,
    GuideSyncRunRequest,
    ScreenshotCaptureFailure,
    ScreenshotCaptureOutcome,
    ScreenshotCaptureResult,
    ScreenshotPolicy,
    ScreenshotValidationAttempt,
    ValidationFinding,
)
from guidesync_agent.services.screenshot_validation import (
    ScreenshotVisionAdapter,
    finalize_screenshot_capture,
    validate_screenshot_capture,
    validate_screenshot_capture_failure,
)
from guidesync_agent.services.validation import ValidationService
from guidesync_agent.storage import project_id_from_run_id
from guidesync_agent.tools.browser import (
    DEFAULT_SCREENSHOT_HEIGHT,
    DEFAULT_SCREENSHOT_WIDTH,
    BrowserToolConfig,
    capture_browser_screenshot,
)
from guidesync_agent.tools.browser_models import BrowserScreenshotRequest

ScreenshotCaptureCallable = Callable[
    [BrowserToolConfig, EvidenceBundle, BrowserScreenshotRequest],
    dict[str, Any],
]


@dataclass
class ScreenshotWorkflowResult:
    captures: list[ScreenshotCaptureOutcome] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    findings: list[ValidationFinding] = field(default_factory=list)


@dataclass(frozen=True)
class ScreenshotWorkflowContext:
    request: GuideSyncRunRequest
    evidence: EvidenceBundle
    file_summaries: list[FileChangeSummary]
    output_dir: Path
    workflow_task_id: str | None = None


@dataclass(frozen=True)
class ScreenshotAttemptResult:
    capture: ScreenshotCaptureOutcome
    validation: ScreenshotValidationAttempt
    usage_finding: ValidationFinding | None = None


def capture_task_screenshots(
    context: ScreenshotWorkflowContext,
    *,
    capture_func: ScreenshotCaptureCallable = capture_browser_screenshot,
    vision_adapter: ScreenshotVisionAdapter | None = None,
) -> ScreenshotWorkflowResult:
    request = context.request
    if request.screenshot_policy == ScreenshotPolicy.DISABLED:
        return ScreenshotWorkflowResult()
    result, expected_text = initialize_screenshot_workflow(context)
    if not request.task_interface_url:
        return screenshot_missing_url_result(result, request.screenshot_policy)
    final_capture = capture_screenshot_attempts(
        context,
        result,
        expected_text,
        capture_func=capture_func,
        vision_adapter=vision_adapter,
    )
    return finalize_screenshot_workflow(context, result, final_capture)


def initialize_screenshot_workflow(
    context: ScreenshotWorkflowContext,
) -> tuple[ScreenshotWorkflowResult, list[str]]:
    result = ScreenshotWorkflowResult()
    context.output_dir.mkdir(parents=True, exist_ok=True)
    expected_text = expected_text_for(context.request.goal, context.file_summaries)
    plan = {
        "policy": context.request.screenshot_policy.value,
        "task_interface_url": context.request.task_interface_url,
        "scenario": "task-interface",
        "expected_text": expected_text,
    }
    result.artifacts["screenshot-plan.json"] = write_json(
        context.output_dir / "screenshot-plan.json",
        plan,
    )
    return result, expected_text


def screenshot_missing_url_result(
    result: ScreenshotWorkflowResult,
    policy: ScreenshotPolicy,
) -> ScreenshotWorkflowResult:
    severity = "error" if policy == ScreenshotPolicy.REQUIRED else "warning"
    result.findings.append(
        ValidationFinding(
            severity=severity,
            check="screenshot.required",
            message="Screenshot policy needs a task interface URL.",
        )
    )
    return result


def capture_screenshot_attempts(
    context: ScreenshotWorkflowContext,
    result: ScreenshotWorkflowResult,
    expected_text: list[str],
    *,
    capture_func: ScreenshotCaptureCallable,
    vision_adapter: ScreenshotVisionAdapter | None,
) -> ScreenshotCaptureOutcome | None:
    request = context.request
    validation_attempts = []
    max_attempts = 2 if request.screenshot_policy == ScreenshotPolicy.REQUIRED else 1
    final_capture: ScreenshotCaptureOutcome | None = None
    for attempt in range(1, max_attempts + 1):
        attempt_result = capture_screenshot_attempt(
            context,
            expected_text,
            attempt,
            capture_func=capture_func,
            vision_adapter=vision_adapter,
        )
        capture = attempt_result.capture
        validation_attempts.append(attempt_result.validation)
        if attempt_result.usage_finding is not None:
            result.findings.append(attempt_result.usage_finding)
        if isinstance(capture, ScreenshotCaptureResult):
            capture = finalize_screenshot_capture(capture, validation_attempts.copy())
        result.captures.append(capture)
        final_capture = capture
        if not attempt_result.validation.retry_recommended or attempt >= max_attempts:
            break
    return final_capture


def capture_screenshot_attempt(
    context: ScreenshotWorkflowContext,
    expected_text: list[str],
    attempt: int,
    *,
    capture_func: ScreenshotCaptureCallable,
    vision_adapter: ScreenshotVisionAdapter | None,
) -> ScreenshotAttemptResult:
    request = context.request
    raw = capture_func(
        BrowserToolConfig(
            enabled=True,
            base_url=request.task_interface_url,
            screenshot_dir=context.output_dir,
        ),
        context.evidence,
        BrowserScreenshotRequest(
            scenario="task-interface",
            url=request.task_interface_url,
            width=DEFAULT_SCREENSHOT_WIDTH,
            height=DEFAULT_SCREENSHOT_HEIGHT,
            expected_text=expected_text,
            attempt=attempt,
        ),
    )
    capture = parse_capture_outcome(
        {
            "scenario": "task-interface",
            "url": request.task_interface_url,
            "attempt": attempt,
            **raw,
        }
    )
    if isinstance(capture, ScreenshotCaptureFailure):
        return ScreenshotAttemptResult(
            capture,
            validate_screenshot_capture_failure(capture),
        )
    validation = validate_screenshot_capture(capture, expected_text, adapter=vision_adapter)
    usage_finding = record_screenshot_model_usage(
        ScreenshotModelUsageContext(
            project_id=project_id_for_request(request),
            run_id=request.run_id,
            workflow_task_id=context.workflow_task_id,
            scenario=capture.scenario,
            url=capture.url,
            image_path=capture.path,
            attempt=validation,
        )
    )
    return ScreenshotAttemptResult(capture, validation, usage_finding)


def finalize_screenshot_workflow(
    context: ScreenshotWorkflowContext,
    result: ScreenshotWorkflowResult,
    final_capture: ScreenshotCaptureOutcome | None,
) -> ScreenshotWorkflowResult:
    if final_capture is None:
        return result
    if isinstance(final_capture, ScreenshotCaptureResult):
        ensure_evidence_contains_capture(context.evidence, final_capture)
    result.artifacts["screenshot-results.json"] = write_json(
        context.output_dir / "screenshot-results.json",
        {"captures": [capture.model_dump(mode="json") for capture in result.captures]},
    )
    if isinstance(final_capture, ScreenshotCaptureResult):
        result.artifacts[Path(final_capture.path).name] = final_capture.path
    result.findings.extend(
        ValidationService().after_screenshot_capture(
            context.request.screenshot_policy,
            final_capture,
        )
    )
    return result


def project_id_for_request(request: GuideSyncRunRequest) -> str | None:
    return next(
        (repository.project_id for repository in request.repositories if repository.project_id),
        None,
    ) or project_id_from_run_id(request.run_id)


def parse_capture_outcome(payload: Mapping[str, object]) -> ScreenshotCaptureOutcome:
    if payload.get("error") is not None:
        return ScreenshotCaptureFailure.model_validate(payload)
    return ScreenshotCaptureResult.model_validate(payload)


def expected_text_for(goal: str, file_summaries: list[FileChangeSummary]) -> list[str]:
    candidates = [
        word.strip(".,:;!?()[]{}").lower()
        for word in goal.split()
        if len(word.strip(".,:;!?()[]{}")) >= 5
    ]
    for summary in file_summaries:
        candidates.extend(summary.docs_to_search[:3])
    seen: set[str] = set()
    expected: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        expected.append(candidate)
        if len(expected) >= 6:
            break
    return expected


def ensure_evidence_contains_capture(
    evidence: EvidenceBundle,
    capture: ScreenshotCaptureResult,
) -> None:
    existing_index = next(
        (
            index
            for index, screenshot in enumerate(evidence.browser_screenshots)
            if screenshot.path == capture.path
        ),
        None,
    )
    notes = (
        evidence.browser_screenshots[existing_index].notes
        if existing_index is not None
        else "Captured by screenshot workflow."
    )
    screenshot = BrowserScreenshotEvidence.from_capture(capture, notes=notes)
    if existing_index is None:
        evidence.browser_screenshots.append(screenshot)
    else:
        evidence.browser_screenshots[existing_index] = screenshot


def write_json(path: Path, payload: Mapping[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return str(path)
