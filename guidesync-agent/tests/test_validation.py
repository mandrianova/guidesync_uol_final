from __future__ import annotations

from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    DocumentationEditResult,
    DocumentationUpdate,
    DocumentationUpdateChange,
    EvidenceBundle,
    EvidenceReference,
    ReviewerCheck,
    ScreenshotPolicy,
    ScreenshotValidationStatus,
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


def test_validation_service_warns_about_missing_screenshot_without_blocking() -> None:
    service = ValidationService()
    coverage_findings = service.after_screenshot_coverage(
        ScreenshotPolicy.REQUIRED,
        EvidenceBundle(),
        None,
    )

    assert coverage_findings[0].severity == "warning"
    assert coverage_findings[0].check == "screenshot.optional"
    assert service.final_status("completed", coverage_findings) == "completed"


def test_required_screenshot_must_be_assigned_to_a_reported_change() -> None:
    service = ValidationService()
    evidence = EvidenceBundle(
        browser_screenshots=[
            BrowserScreenshotEvidence(
                scenario="unreported-change",
                change_id="change-not-in-report",
                url="https://example.com/product",
                path="/tmp/unreported.png",
                prepared_artifact_name="unreported.png",
                publication_approved=True,
                validation_status=ScreenshotValidationStatus.PASSED,
            )
        ]
    )
    update = valid_update().model_copy(
        update={
            "changes": [
                DocumentationUpdateChange(
                    id="reported-change",
                    title="Reported change",
                    summary="A supported release change.",
                    user_facing_change="Users can use the reported change.",
                    evidence_refs=["diff:reported-change"],
                )
            ]
        }
    )

    findings = service.after_screenshot_coverage(
        ScreenshotPolicy.REQUIRED,
        evidence,
        update,
    )

    assert findings[0].check == "screenshot.optional"
    assert "assigned to a reported change" in findings[0].message


def test_required_screenshot_rejects_image_when_report_has_no_changes() -> None:
    service = ValidationService()
    evidence = EvidenceBundle(
        browser_screenshots=[
            BrowserScreenshotEvidence(
                scenario="orphaned-image",
                change_id="unreported-change",
                url="https://example.com/product",
                path="/tmp/orphaned.png",
                prepared_artifact_name="orphaned.png",
                publication_approved=True,
                validation_status=ScreenshotValidationStatus.PASSED,
            )
        ]
    )
    update = valid_update().model_copy(update={"changes": []})

    findings = service.after_screenshot_coverage(
        ScreenshotPolicy.REQUIRED,
        evidence,
        update,
    )

    assert findings[0].check == "screenshot.optional"


def test_required_screenshot_accepts_prepared_image_for_reported_change() -> None:
    service = ValidationService()
    evidence = EvidenceBundle(
        browser_screenshots=[
            BrowserScreenshotEvidence(
                scenario="reported-change",
                change_id="reported-change",
                url="https://example.com/product",
                path="/tmp/reported.png",
                prepared_artifact_name="reported.png",
                publication_approved=True,
                validation_status=ScreenshotValidationStatus.PASSED,
            )
        ]
    )
    update = valid_update().model_copy(
        update={
            "changes": [
                DocumentationUpdateChange(
                    id="reported-change",
                    title="Reported change",
                    summary="A supported release change.",
                    user_facing_change="Users can use the reported change.",
                    evidence_refs=["diff:reported-change"],
                )
            ]
        }
    )

    assert (
        service.after_screenshot_coverage(
            ScreenshotPolicy.REQUIRED,
            evidence,
            update,
        )
        == []
    )


def test_required_screenshot_rejects_approval_without_passed_validation() -> None:
    service = ValidationService()
    evidence = EvidenceBundle(
        browser_screenshots=[
            BrowserScreenshotEvidence(
                scenario="reported-change",
                change_id="reported-change",
                url="https://example.com/product",
                path="/tmp/reported.png",
                prepared_artifact_name="reported.png",
                publication_approved=True,
                validation_status=ScreenshotValidationStatus.FAILED,
            )
        ]
    )
    update = valid_update().model_copy(
        update={
            "changes": [
                DocumentationUpdateChange(
                    id="reported-change",
                    title="Reported change",
                    summary="A supported release change.",
                    user_facing_change="Users can use the reported change.",
                )
            ]
        }
    )

    findings = service.after_screenshot_coverage(
        ScreenshotPolicy.REQUIRED,
        evidence,
        update,
    )

    assert findings[0].check == "screenshot.optional"


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
