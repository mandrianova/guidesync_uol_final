from __future__ import annotations

import logging

from guidesync_agent.agent_runtime.screenshot_capture import (
    run_screenshot_capture_agent,
)
from guidesync_agent.reports import write_reports
from guidesync_agent.schemas import (
    GuideSyncRunResult,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ScreenshotCaptureWorkflowInput,
    ScreenshotCaptureWorkflowResult,
    ScreenshotValidationStatus,
    ValidationFinding,
)
from guidesync_agent.services.reports.publication import build_publication_report
from guidesync_agent.services.ui_evidence.screenshots import (
    screenshot_evidence_artifacts,
)
from guidesync_agent.storage import create_run_store

logger = logging.getLogger(__name__)
SCREENSHOT_FINDING_CHECK = "screenshot.optional"


async def execute_screenshot_capture(
    task: ProjectWorkflowTask,
) -> ProjectWorkflowTask:
    task_input = ScreenshotCaptureWorkflowInput.model_validate(task.input)
    run = require_screenshot_run(task_input.run_id)
    update = run.update
    if update is None:  # narrowed by require_screenshot_run at the storage boundary
        raise ValueError("Screenshot capture requires a completed release report.")
    summary, transcript_id = await run_screenshot_capture_agent(
        run,
        project_id=task.project_id,
        workflow_task_id=task.id,
    )
    request_change_ids = {item.change_id for item in update.screenshot_requests}
    captures = [
        item
        for item in run.evidence.browser_screenshots
        if item.change_id in request_change_ids
    ]
    approved = [
        item
        for item in captures
        if item.publication_approved
        and item.validation_status is ScreenshotValidationStatus.PASSED
    ]
    warning = None
    if not approved:
        warning = screenshot_capture_warning(summary)
        logger.error(
            "Screenshot capture produced no publication-approved image for run %s: %s",
            run.run_id,
            " ".join(summary.split()) or "No detailed reason was returned.",
        )
    persist_screenshot_result(run, warning=warning)
    result = ScreenshotCaptureWorkflowResult(
        report_run_id=run.run_id,
        request_count=len(update.screenshot_requests),
        capture_count=len(captures),
        approved_count=len(approved),
        transcript_id=transcript_id,
        summary=summary,
    )
    return task.model_copy(
        update={
            "result": result,
            "warnings": [*task.warnings, warning] if warning else task.warnings,
        }
    )


def screenshot_capture_warning(summary: str) -> str:
    reason = summary.strip() or "The capture agent did not return a detailed reason."
    return (
        f"No screenshots were added. {reason} "
        "The release report remains available because screenshots are optional."
    )


def fail_screenshot_capture(task: ProjectWorkflowTask, *, retrying: bool) -> None:
    if retrying or task.kind is not ProjectWorkflowTaskKind.SCREENSHOT_CAPTURE:
        return
    task_input = ScreenshotCaptureWorkflowInput.model_validate(task.input)
    run = create_run_store().get(task_input.run_id)
    if run is None or run.update is None:
        return
    try:
        persist_screenshot_result(
            run,
            warning=(
                f"Screenshot capture failed: {task.error_message or 'unknown error'}. "
                "The release report remains available without screenshots."
            ),
        )
    except Exception:  # terminal workflow boundary must retain task failure
        logger.exception("Could not persist optional screenshot failure for run %s.", run.run_id)


def persist_screenshot_result(
    run: GuideSyncRunResult,
    *,
    warning: str | None,
) -> None:
    findings = [
        finding for finding in run.findings if finding.check != SCREENSHOT_FINDING_CHECK
    ]
    if warning:
        findings.append(
            ValidationFinding(
                severity="warning",
                check=SCREENSHOT_FINDING_CHECK,
                message=warning,
            )
        )
    run.findings = findings
    run.artifacts.update(
        screenshot_evidence_artifacts(run.request.report.output_dir, run.evidence)
    )
    run.artifacts = write_reports(run)
    store = create_run_store()
    store.save(run, build_publication_report(run))
    store.record_run_event(
        run.run_id,
        run.status,
        warning or "Optional screenshot capture completed.",
        "screenshots",
    )


def require_screenshot_run(run_id: str) -> GuideSyncRunResult:
    run = create_run_store().get(run_id)
    if run is None:
        raise ValueError(f"Run not found: {run_id}")
    if run.status != "completed" or run.update is None:
        raise ValueError("Screenshot capture requires a completed release report.")
    if not (run.request.task_interface_url or "").strip():
        raise ValueError("Screenshot capture requires a task interface URL.")
    if not run.update.screenshot_requests:
        raise ValueError("The release report has no planned screenshot requests.")
    return run
