from __future__ import annotations

import re

from guidesync_agent.schemas import (
    DocumentationEditResult,
    DocumentationUpdate,
    EvidenceBundle,
    FileChangeSummary,
    ScreenshotCaptureResult,
    ScreenshotPolicy,
    ValidationFinding,
)
from guidesync_agent.tools.validation import validate_tool_result

TECHNICAL_LEAK_PATTERNS = (
    r"\b[a-f0-9]{8,40}\b",
    r"\bsrc/",
    r"\bapp/",
    r"\bproject/",
    r"\bcomponents/",
    r"\broutes/",
)


def validate_update(
    update: DocumentationUpdate | None,
    evidence: EvidenceBundle,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    if update is None:
        return [
            ValidationFinding(
                severity="error",
                check="output",
                message="No release notes were generated.",
            )
        ]
    required_text = {
        "title": update.title,
        "summary": update.summary,
        "user_facing_change": update.user_facing_change,
        "proposed_update_markdown": update.proposed_update_markdown,
    }
    for field, value in required_text.items():
        if not value.strip():
            findings.append(
                ValidationFinding(
                    severity="error",
                    check="required-section",
                    message=f"`{field}` is empty.",
                )
            )
    if not update.evidence_used:
        findings.append(
            ValidationFinding(
                severity="error",
                check="evidence",
                message="The release notes draft does not cite any evidence.",
            )
        )
    if evidence.commits and not any(ref.source.startswith("git:") for ref in update.evidence_used):
        findings.append(
            ValidationFinding(
                severity="warning",
                check="evidence",
                message="Repository evidence exists, but no git evidence reference was cited.",
            )
        )
    if update.documentation_edit and update.documentation_edit.changed_docs:
        changed_docs = update.documentation_edit.changed_docs
        if not any(ref.source.startswith("doc-change:") for ref in update.evidence_used):
            findings.append(
                ValidationFinding(
                    severity="error",
                    check="documentation-link",
                    message=(
                        "Documentation edit exists, but no doc-change evidence reference "
                        "was cited."
                    ),
                )
            )
        missing_doc_links = [
            path for path in changed_docs if path not in update.proposed_update_markdown
        ]
        if missing_doc_links:
            findings.append(
                ValidationFinding(
                    severity="error",
                    check="documentation-link",
                    message=(
                        "Release notes draft does not link changed documentation: "
                        + ", ".join(missing_doc_links)
                    ),
                )
            )
    user_copy = "\n".join(
        [update.title, update.summary, update.user_facing_change, update.proposed_update_markdown]
    )
    for pattern in TECHNICAL_LEAK_PATTERNS:
        if re.search(pattern, user_copy):
            findings.append(
                ValidationFinding(
                    severity="warning",
                    check="technical-leakage",
                    message=f"Potential technical detail in user-facing copy: `{pattern}`.",
                )
            )
    if len(update.reviewer_checks) < 2:
        findings.append(
            ValidationFinding(
                severity="warning",
                check="reviewer-checks",
                message="Expected at least two reviewer checks.",
            )
        )
    return findings


class ValidationService:
    def after_tool_result(
        self,
        tool_name: str,
        result: object,
        *,
        blocking: bool = False,
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        for finding in validate_tool_result(tool_name, result):
            severity = finding.severity
            if severity == "error" and not blocking:
                severity = "warning"
            findings.append(
                ValidationFinding(
                    severity=severity,
                    check=finding.check,
                    message=finding.message,
                    evidence_refs=finding.evidence_refs,
                    artifact_refs=finding.artifact_refs,
                )
            )
        return findings

    def after_file_summary(self, summary: FileChangeSummary) -> list[ValidationFinding]:
        if not summary.needs_main_agent_review:
            return []
        artifact_refs = [summary.artifact_uri] if summary.artifact_uri else []
        return [
            ValidationFinding(
                severity="warning",
                check="file-summary.review",
                message=f"`{summary.path}` needs main-agent review before documentation changes.",
                evidence_refs=[f"file-summary:{summary.repository_id}:{summary.path}"],
                artifact_refs=artifact_refs,
            )
        ]

    def after_documentation_edit(
        self,
        edit: DocumentationEditResult,
    ) -> list[ValidationFinding]:
        artifact_refs = [edit.patch_artifact_uri] if edit.patch_artifact_uri else []
        evidence_refs = [
            f"doc-change:{edit.repository_id}:{path}" for path in edit.changed_docs
        ]
        findings = [
            ValidationFinding(
                severity="warning",
                check="documentation-edit.warning",
                message=warning,
                evidence_refs=evidence_refs,
                artifact_refs=artifact_refs,
            )
            for warning in edit.warnings
        ]
        if edit.changed_docs and not edit.ok:
            findings.append(
                ValidationFinding(
                    severity="warning",
                    check="documentation-edit.commit",
                    message=(
                        "Documentation edit did not create a local commit; patch artifact saved."
                    ),
                    evidence_refs=evidence_refs,
                    artifact_refs=artifact_refs,
                )
            )
        return findings

    def after_screenshot_capture(
        self,
        policy: ScreenshotPolicy,
        capture: ScreenshotCaptureResult,
    ) -> list[ValidationFinding]:
        artifact_refs = [capture.path] if capture.path else []
        evidence_refs = [f"screenshot:{capture.scenario}"]
        if capture.ok and not capture.blank:
            return self._valid_screenshot_findings(capture, evidence_refs, artifact_refs)

        severity = "error" if policy == ScreenshotPolicy.REQUIRED else "warning"
        message = capture.error or "Screenshot capture failed."
        if capture.blank:
            message = "Screenshot capture produced a blank image."
        return [
            ValidationFinding(
                severity=severity,
                check="screenshot.capture",
                message=message,
                evidence_refs=evidence_refs,
                artifact_refs=artifact_refs,
            )
        ]

    def after_release_notes(
        self,
        update: DocumentationUpdate | None,
        evidence: EvidenceBundle,
    ) -> list[ValidationFinding]:
        return validate_update(update, evidence)

    def final_status(
        self,
        current_status: str,
        findings: list[ValidationFinding],
    ) -> str:
        if current_status != "completed":
            return current_status
        if any(is_blocking_finding(finding) for finding in findings):
            return "failed"
        return current_status

    def _valid_screenshot_findings(
        self,
        capture: ScreenshotCaptureResult,
        evidence_refs: list[str],
        artifact_refs: list[str],
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        if capture.missing_text:
            findings.append(
                ValidationFinding(
                    severity="warning",
                    check="screenshot.expected-text",
                    message=(
                        "Screenshot did not include expected text: "
                        + ", ".join(capture.missing_text)
                    ),
                    evidence_refs=evidence_refs,
                    artifact_refs=artifact_refs,
                )
            )
        if capture.console_errors or capture.network_errors:
            findings.append(
                ValidationFinding(
                    severity="warning",
                    check="screenshot.runtime",
                    message="Screenshot captured with console or network errors.",
                    evidence_refs=evidence_refs,
                    artifact_refs=artifact_refs,
                )
            )
        return findings


def is_blocking_finding(finding: ValidationFinding) -> bool:
    if finding.severity != "error":
        return False
    return finding.check in {
        "documentation-link",
        "output",
        "required-section",
        "screenshot.capture",
        "screenshot.required",
    }
