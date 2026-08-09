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
    ScreenshotActionKind,
    ScreenshotCaptureFailure,
    ScreenshotCaptureOutcome,
    ScreenshotCaptureResult,
    ScreenshotPlan,
    ScreenshotPlanItem,
    ScreenshotPolicy,
    ScreenshotValidationAttempt,
    ValidationFinding,
)
from guidesync_agent.services.screenshot_planning import build_screenshot_plan
from guidesync_agent.services.screenshot_validation import (
    ScreenshotVisionAdapter,
    finalize_screenshot_capture,
    validate_screenshot_capture,
    validate_screenshot_capture_failure,
)
from guidesync_agent.services.validation import ValidationService
from guidesync_agent.storage import project_id_from_run_id
from guidesync_agent.tools.browser import (
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
    result, plan = initialize_screenshot_workflow(context)
    if not plan.items:
        return result
    if not request.task_interface_url:
        return screenshot_missing_url_result(result, request.screenshot_policy)
    final_captures = [
        capture_screenshot_attempts(
            context,
            result,
            item,
            capture_func=capture_func,
            vision_adapter=vision_adapter,
        )
        for item in plan.items
    ]
    return finalize_screenshot_workflow(context, result, final_captures)


def initialize_screenshot_workflow(
    context: ScreenshotWorkflowContext,
) -> tuple[ScreenshotWorkflowResult, ScreenshotPlan]:
    result = ScreenshotWorkflowResult()
    context.output_dir.mkdir(parents=True, exist_ok=True)
    plan = build_screenshot_plan(context.request, context.file_summaries)
    result.artifacts["screenshot-plan.json"] = write_json(
        context.output_dir / "screenshot-plan.json",
        plan.model_dump(mode="json"),
    )
    return result, plan


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
    item: ScreenshotPlanItem,
    *,
    capture_func: ScreenshotCaptureCallable,
    vision_adapter: ScreenshotVisionAdapter | None,
) -> ScreenshotCaptureOutcome | None:
    validation_attempts = []
    max_attempts = item.max_attempts
    final_capture: ScreenshotCaptureOutcome | None = None
    for attempt in range(1, max_attempts + 1):
        attempt_result = capture_screenshot_attempt(
            context,
            item,
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
    item: ScreenshotPlanItem,
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
            timeout_ms=item.timeout_ms,
        ),
        context.evidence,
        BrowserScreenshotRequest(
            scenario=item.id,
            url=item.route,
            steps=browser_steps_for_plan_item(item),
            width=item.viewport.width,
            height=item.viewport.height,
            expected_text=item.expected_text,
            rejected_text=item.rejected_text,
            attempt=attempt,
            plan_item=item,
        ),
    )
    capture = parse_capture_outcome(
        {
            "scenario": item.id,
            "url": request.task_interface_url,
            "attempt": attempt,
            "scenario_id": item.id,
            "plan_item_id": item.id,
            "change_id": item.change_id,
            "claim_id": item.claim_id,
            "route": item.route,
            "theme": item.theme,
            "requested_state": item.requested_state,
            "rejected_text": item.rejected_text,
            "caption": item.caption,
            "alt_text": item.alt_text,
            "capture_target": item.capture_target,
            **raw,
        }
    )
    if isinstance(capture, ScreenshotCaptureFailure):
        return ScreenshotAttemptResult(
            capture,
            validate_screenshot_capture_failure(capture),
        )
    validation = validate_screenshot_capture(
        capture,
        item.expected_text,
        rejected_text=item.rejected_text,
        locale=request.report.locale,
        adapter=vision_adapter,
    )
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


def browser_steps_for_plan_item(item: ScreenshotPlanItem) -> list[str]:
    steps = []
    for action in item.actions:
        if action.kind is ScreenshotActionKind.NAVIGATE:
            steps.append(f"goto {action.route}")
            continue
        if action.kind is ScreenshotActionKind.WAIT:
            steps.append(f"wait {action.wait_ms}")
            continue
        if action.locator_kind is None or action.locator is None:
            raise ValueError("semantic screenshot action is missing its locator")
        locator_kind = action.locator_kind.value.replace("_", "")
        locator = f"{locator_kind}={action.locator}"
        if action.role_name:
            locator = f"{locator} name={action.role_name}"
        steps.append(f"{action.kind.value} {locator}")
    return steps


def finalize_screenshot_workflow(
    context: ScreenshotWorkflowContext,
    result: ScreenshotWorkflowResult,
    final_captures: list[ScreenshotCaptureOutcome | None],
) -> ScreenshotWorkflowResult:
    captures = [capture for capture in final_captures if capture is not None]
    if not captures:
        return result
    for capture in captures:
        if isinstance(capture, ScreenshotCaptureResult):
            ensure_evidence_contains_capture(context.evidence, capture)
    result.artifacts["screenshot-results.json"] = write_json(
        context.output_dir / "screenshot-results.json",
        {"captures": [capture.model_dump(mode="json") for capture in result.captures]},
    )
    for capture in result.captures:
        if isinstance(capture, ScreenshotCaptureResult):
            add_capture_artifacts(result.artifacts, capture)
    for capture in captures:
        result.findings.extend(
            ValidationService().after_screenshot_capture(
                context.request.screenshot_policy,
                capture,
            )
        )
    return result


def add_capture_artifacts(
    artifacts: dict[str, str],
    capture: ScreenshotCaptureResult,
) -> None:
    if capture.raw_path:
        artifacts[Path(capture.raw_path).name] = capture.raw_path
    if capture.publication_approved and capture.prepared_artifact_name:
        artifacts[capture.prepared_artifact_name] = capture.path


def screenshot_evidence_artifacts(
    output_dir: Path,
    evidence: EvidenceBundle,
) -> dict[str, str]:
    if not evidence.browser_screenshots:
        return {}
    screenshot_dir = output_dir / "screenshots"
    artifacts = {
        "screenshot-evidence.json": write_json(
            screenshot_dir / "screenshot-evidence.json",
            {
                "screenshots": [
                    screenshot.model_dump(mode="json")
                    for screenshot in evidence.browser_screenshots
                ]
            },
        )
    }
    for screenshot in evidence.browser_screenshots:
        if screenshot.raw_path:
            artifacts[Path(screenshot.raw_path).name] = screenshot.raw_path
        if screenshot.publication_approved and screenshot.prepared_artifact_name:
            artifacts[screenshot.prepared_artifact_name] = screenshot.path
    return artifacts


def project_id_for_request(request: GuideSyncRunRequest) -> str | None:
    return next(
        (repository.project_id for repository in request.repositories if repository.project_id),
        None,
    ) or project_id_from_run_id(request.run_id)


def parse_capture_outcome(payload: Mapping[str, object]) -> ScreenshotCaptureOutcome:
    if payload.get("error") is not None:
        return ScreenshotCaptureFailure.model_validate(payload)
    return ScreenshotCaptureResult.model_validate(payload)


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
