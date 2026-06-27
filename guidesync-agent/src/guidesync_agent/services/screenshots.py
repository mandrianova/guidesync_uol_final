from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    EvidenceBundle,
    FileChangeSummary,
    GuideSyncRunRequest,
    ScreenshotCaptureResult,
    ScreenshotPolicy,
    ValidationFinding,
)
from guidesync_agent.services.screenshot_model_usage import (
    ScreenshotModelUsageContext,
    record_screenshot_model_usage,
)
from guidesync_agent.services.screenshot_validation import (
    ScreenshotVisionAdapter,
    finalize_screenshot_capture,
    validate_screenshot_capture,
)
from guidesync_agent.services.validation import ValidationService
from guidesync_agent.storage import project_id_from_run_id
from guidesync_agent.tools.browser import (
    DEFAULT_SCREENSHOT_HEIGHT,
    DEFAULT_SCREENSHOT_WIDTH,
    BrowserToolConfig,
    capture_browser_screenshot,
)

ScreenshotCaptureCallable = Callable[..., dict[str, Any]]


@dataclass
class ScreenshotWorkflowResult:
    captures: list[ScreenshotCaptureResult] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    findings: list[ValidationFinding] = field(default_factory=list)


def capture_task_screenshots(
    request: GuideSyncRunRequest,
    evidence: EvidenceBundle,
    file_summaries: list[FileChangeSummary],
    *,
    output_dir: Path,
    capture_func: ScreenshotCaptureCallable = capture_browser_screenshot,
    vision_adapter: ScreenshotVisionAdapter | None = None,
    workflow_task_id: str | None = None,
) -> ScreenshotWorkflowResult:
    if request.screenshot_policy == ScreenshotPolicy.DISABLED:
        return ScreenshotWorkflowResult()

    result = ScreenshotWorkflowResult()
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_text = expected_text_for(request.goal, file_summaries)
    plan = {
        "policy": request.screenshot_policy.value,
        "task_interface_url": request.task_interface_url,
        "scenario": "task-interface",
        "expected_text": expected_text,
    }
    result.artifacts["screenshot-plan.json"] = write_json(
        output_dir / "screenshot-plan.json",
        plan,
    )

    if not request.task_interface_url:
        severity = "error" if request.screenshot_policy == ScreenshotPolicy.REQUIRED else "warning"
        result.findings.append(
            ValidationFinding(
                severity=severity,
                check="screenshot.required",
                message="Screenshot policy needs a task interface URL.",
            )
        )
        return result

    validation_attempts = []
    max_attempts = 2 if request.screenshot_policy == ScreenshotPolicy.REQUIRED else 1
    final_capture: ScreenshotCaptureResult | None = None
    for attempt in range(1, max_attempts + 1):
        raw = call_capture(
            capture_func,
            attempt=attempt,
            config=BrowserToolConfig(
                enabled=True,
                base_url=request.task_interface_url,
                screenshot_dir=output_dir,
            ),
            evidence=evidence,
            scenario="task-interface",
            url=request.task_interface_url,
            steps=[],
            width=DEFAULT_SCREENSHOT_WIDTH,
            height=DEFAULT_SCREENSHOT_HEIGHT,
            expected_text=expected_text,
        )
        capture = ScreenshotCaptureResult.model_validate(
            {
                "scenario": "task-interface",
                "url": request.task_interface_url,
                "attempt": attempt,
                **raw,
            }
        )
        validation = validate_screenshot_capture(
            capture,
            expected_text,
            adapter=vision_adapter,
        )
        usage_finding = record_screenshot_model_usage(
            ScreenshotModelUsageContext(
                project_id=project_id_for_request(request),
                run_id=request.run_id,
                workflow_task_id=workflow_task_id,
                scenario=capture.scenario,
                url=capture.url,
                image_path=capture.path,
                attempt=validation,
            )
        )
        if usage_finding is not None:
            result.findings.append(usage_finding)
        validation_attempts.append(validation)
        capture = finalize_screenshot_capture(capture, validation_attempts.copy())
        result.captures.append(capture)
        final_capture = capture
        if not validation.retry_recommended or attempt >= max_attempts:
            break

    if final_capture is None:
        return result
    ensure_evidence_contains_capture(evidence, final_capture)
    result.artifacts["screenshot-results.json"] = write_json(
        output_dir / "screenshot-results.json",
        {"captures": [capture.model_dump(mode="json") for capture in result.captures]},
    )
    if final_capture.path:
        result.artifacts[Path(final_capture.path).name] = final_capture.path
    result.findings.extend(
        ValidationService().after_screenshot_capture(request.screenshot_policy, final_capture)
    )
    return result


def project_id_for_request(request: GuideSyncRunRequest) -> str | None:
    return next(
        (repository.project_id for repository in request.repositories if repository.project_id),
        None,
    ) or project_id_from_run_id(request.run_id)


def call_capture(
    capture_func: ScreenshotCaptureCallable,
    *,
    attempt: int,
    **kwargs: Any,
) -> dict[str, Any]:
    if accepts_attempt(capture_func):
        kwargs["attempt"] = attempt
    return capture_func(**kwargs)


def accepts_attempt(capture_func: ScreenshotCaptureCallable) -> bool:
    signature = inspect.signature(capture_func)
    return "attempt" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


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
    if not capture.ok or not capture.path:
        return
    if any(item.path == capture.path for item in evidence.browser_screenshots):
        return
    evidence.browser_screenshots.append(
        BrowserScreenshotEvidence(
            scenario=capture.scenario,
            url=capture.url,
            path=capture.path,
            title=capture.title,
            viewport=capture.viewport,
            visible_text=capture.visible_text,
            matched_text=capture.matched_text,
            missing_text=capture.missing_text,
            console_errors=capture.console_errors,
            network_errors=capture.network_errors,
            image_hash=capture.image_hash,
            blank=capture.blank,
            ocr_text=capture.ocr_text,
            validation_status=capture.validation_status,
            validation_reasons=capture.validation_reasons,
            attempts=max(len(capture.validation_attempts), capture.attempt),
            notes="Captured by screenshot workflow.",
        )
    )


def write_json(path: Path, payload: Mapping[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return str(path)
