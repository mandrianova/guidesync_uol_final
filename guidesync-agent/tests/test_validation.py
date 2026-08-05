from __future__ import annotations

from guidesync_agent.schemas import (
    DocumentationEditResult,
    DocumentationUpdate,
    EvidenceBundle,
    EvidenceReference,
    OperationError,
    ReviewerCheck,
    ScreenshotCaptureFailure,
    ScreenshotPolicy,
    ValidationFinding,
)
from guidesync_agent.services.validation import ValidationService, validate_update


def valid_update(markdown: str = "Explain the user workflow.") -> DocumentationUpdate:
    return DocumentationUpdate(
        title="Domain workflow update",
        summary="Explain the current custom-domain workflow.",
        user_facing_change="Users verify and bind a custom domain from workspace settings.",
        proposed_update_markdown=markdown,
        evidence_used=[
            EvidenceReference(
                source="git:repo:12345678",
                detail="Add custom domain workflow",
                relevance="Grounds the proposed release note.",
            )
        ],
        reviewer_checks=[
            ReviewerCheck(name="Evidence coverage", status="pass", notes="Evidence is cited."),
            ReviewerCheck(name="Human review", status="required", notes="Check UI names."),
        ],
    )


def test_validate_update_accepts_evidence_backed_output() -> None:
    findings = validate_update(valid_update(), EvidenceBundle())

    assert findings == []


def test_validate_update_warns_about_technical_leakage() -> None:
    findings = validate_update(
        valid_update("Tell users to edit src/routes/domain.py."),
        EvidenceBundle(),
    )

    assert any(finding.check == "technical-leakage" for finding in findings)


def test_validate_update_requires_documentation_links_for_doc_edits() -> None:
    update = valid_update("Explain the workflow without linking changed docs.")
    update.documentation_edit = DocumentationEditResult(
        repository_id="repo-docs",
        docs_path="docs",
        target_path="docs/guide.md",
        changed_docs=["docs/guide.md"],
    )

    findings = validate_update(update, EvidenceBundle())

    assert any(finding.check == "documentation-link" for finding in findings)


def test_validation_service_marks_missing_doc_link_blocking() -> None:
    update = valid_update("Explain the workflow without linking changed docs.")
    update.documentation_edit = DocumentationEditResult(
        repository_id="repo-docs",
        docs_path="docs",
        target_path="docs/guide.md",
        changed_docs=["docs/guide.md"],
    )
    service = ValidationService()

    findings = service.after_release_notes(update, EvidenceBundle())

    assert service.final_status("completed", findings) == "failed"


def test_validation_service_blocks_required_screenshot_failure() -> None:
    service = ValidationService()
    findings = service.after_screenshot_capture(
        ScreenshotPolicy.REQUIRED,
        ScreenshotCaptureFailure(
            scenario="task-interface",
            url="http://127.0.0.1:5173",
            error=OperationError(
                code="browser_unavailable",
                message="No browser available.",
            ),
        ),
    )

    assert findings[0].severity == "error"
    assert service.final_status("completed", findings) == "failed"


def test_validation_service_keeps_noncritical_tool_warning_nonblocking() -> None:
    service = ValidationService()

    findings = service.after_tool_result(
        "search_files",
        {"error": {"message": "search timed out"}},
        blocking=False,
    )

    assert findings[0].severity == "warning"
    assert service.final_status("completed", findings) == "completed"


def test_validation_service_reads_structured_error_without_ok_flag() -> None:
    service = ValidationService()

    findings = service.after_tool_result(
        "capture_ui_screenshot",
        {
            "error": {
                "code": "browser_unavailable",
                "message": "No browser available.",
                "retryable": False,
            }
        },
        blocking=True,
    )

    assert findings[0].severity == "error"
    assert findings[0].check == "capture_ui_screenshot.error"
    assert findings[0].message == "No browser available."


def test_validation_service_keeps_nonblocking_evidence_error_completed() -> None:
    service = ValidationService()

    status = service.final_status(
        "completed",
        [
            ValidationFinding(
                severity="error",
                check="evidence",
                message="Release notes draft does not cite evidence.",
            )
        ],
    )

    assert status == "completed"
