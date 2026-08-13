from __future__ import annotations

from guidesync_agent.schemas import (
    DocumentationUpdate,
    DocumentationUpdateChange,
    DocumentationUpdateModelOutput,
    EvidenceReference,
    ReleaseScreenshotRequest,
    ReviewerCheck,
)
from guidesync_agent.services.stable_ids import stable_id


def documentation_update_from_model_output(output: object) -> DocumentationUpdate:
    if isinstance(output, DocumentationUpdate):
        return output
    model_output = DocumentationUpdateModelOutput.model_validate(output)
    evidence_refs = [
        EvidenceReference(
            source=source,
            detail="Cited by the release-notes model output.",
            relevance="Model-selected evidence reference.",
        )
        for source in model_output.evidence_refs
    ]
    reviewer_notes = model_output.reviewer_notes.strip()
    reviewer_checks = [
        ReviewerCheck(
            name="Evidence coverage",
            status="pass" if evidence_refs else "warning",
            notes=(
                "The model cited evidence references."
                if evidence_refs
                else "The model did not cite evidence references."
            ),
        ),
        ReviewerCheck(
            name="Human review",
            status="required",
            notes=reviewer_notes or "Review user impact, terminology, and tone.",
        ),
    ]
    return DocumentationUpdate(
        title=model_output.title,
        summary=model_output.summary,
        user_facing_change=model_output.user_facing_change,
        proposed_update_markdown=model_output.proposed_update_markdown,
        evidence_used=evidence_refs,
        reviewer_checks=reviewer_checks,
        changes=documentation_update_changes(model_output),
        screenshot_requests=screenshot_requests(model_output),
        risks_or_limitations=model_output.risks_or_limitations,
        suggested_improvements=model_output.suggested_improvements,
    )


def documentation_update_changes(
    output: DocumentationUpdateModelOutput,
) -> list[DocumentationUpdateChange]:
    return [
        DocumentationUpdateChange(
            id=change_id,
            title=title,
            summary=summary,
            user_facing_change=user_facing_detail,
            how_to_markdown=how_to_markdown,
            evidence_refs=split_change_evidence_refs(evidence_refs),
        )
        for (
            change_id,
            title,
            summary,
            user_facing_detail,
            how_to_markdown,
            evidence_refs,
        ) in zip(
            output.change_ids,
            output.change_titles,
            output.change_summaries,
            output.change_user_facing_details,
            output.change_how_to_markdown,
            output.change_evidence_refs,
            strict=True,
        )
    ]


def split_change_evidence_refs(value: str) -> list[str]:
    normalized = value.replace("\\n", "\n")
    return list(dict.fromkeys(line.strip() for line in normalized.splitlines() if line.strip()))


def screenshot_requests(
    output: DocumentationUpdateModelOutput,
) -> list[ReleaseScreenshotRequest]:
    return [
        ReleaseScreenshotRequest(
            id=stable_id("screenshot-request", change_id, claim, purpose),
            change_id=change_id,
            claim=claim,
            purpose=purpose,
            route_hint=route_hint,
            evidence_refs=split_change_evidence_refs(evidence_refs),
        )
        for change_id, claim, purpose, route_hint, evidence_refs in zip(
            output.screenshot_change_ids,
            output.screenshot_claims,
            output.screenshot_purposes,
            output.screenshot_route_hints,
            output.screenshot_evidence_refs,
            strict=True,
        )
    ]
