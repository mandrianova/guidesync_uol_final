from __future__ import annotations

import re

from guidesync_agent.schemas import DocumentationUpdate, EvidenceBundle, ValidationFinding

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
                message="No documentation update was generated.",
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
                message="The update does not cite any evidence.",
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
