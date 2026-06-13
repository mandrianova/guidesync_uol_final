from __future__ import annotations

from guidesync_agent.schemas import (
    DocumentationUpdate,
    EvidenceBundle,
    EvidenceReference,
    ReviewerCheck,
)
from guidesync_agent.validation import validate_update


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
                relevance="Grounds the proposed documentation change.",
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
