from __future__ import annotations

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
from guidesync_agent.services.validation import ValidationService
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

    raw = capture_func(
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
            **raw,
        }
    )
    result.captures.append(capture)
    ensure_evidence_contains_capture(evidence, capture)
    result.artifacts["screenshot-results.json"] = write_json(
        output_dir / "screenshot-results.json",
        {"captures": [capture.model_dump(mode="json")]},
    )
    if capture.path:
        result.artifacts[Path(capture.path).name] = capture.path
    result.findings.extend(
        ValidationService().after_screenshot_capture(request.screenshot_policy, capture)
    )
    return result


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
            notes="Captured by screenshot workflow.",
        )
    )


def write_json(path: Path, payload: Mapping[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return str(path)
