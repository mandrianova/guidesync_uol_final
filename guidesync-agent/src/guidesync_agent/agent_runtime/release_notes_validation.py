from __future__ import annotations

import re
from pathlib import Path

from guidesync_agent.agent_runtime.release_notes_output import split_change_evidence_refs
from guidesync_agent.schemas import (
    AnalysisArtifactManifest,
    DocumentationUpdateModelOutput,
    ScreenshotPolicy,
)
from guidesync_agent.services.publication_reports import (
    has_publishable_screenshot_for_changes,
)
from guidesync_agent.tools.evidence import EvidenceAgentDeps

IMPROVEMENT_STEMS = ("enhanc", "improv", "optimiz", "refin")


def release_notes_output_issue(
    output: DocumentationUpdateModelOutput,
    deps: EvidenceAgentDeps,
) -> str | None:
    issue = (
        release_notes_language_issue(output, deps.report_locale)
        or release_notes_evidence_consistency_issue(output, deps.analysis_manifest)
        or release_notes_knowledge_context_issue(output, deps)
    )
    if issue is not None:
        return issue
    return release_notes_screenshot_issue(output, deps)


def release_notes_screenshot_issue(
    output: DocumentationUpdateModelOutput,
    deps: EvidenceAgentDeps,
) -> str | None:
    if release_notes_screenshot_requirement_satisfied(output, deps):
        return None

    candidates = deps.screenshot_candidate_change_ids
    candidate_hint = f" Candidate change IDs: {', '.join(candidates)}." if candidates else ""
    return (
        "Screenshot policy is required. Use capture_ui_screenshot to add at least one "
        "publication-approved UI image assigned to a reported change before returning the "
        "report." + candidate_hint
    )


def release_notes_screenshot_requirement_satisfied(
    output: DocumentationUpdateModelOutput,
    deps: EvidenceAgentDeps,
) -> bool:
    if deps.screenshot_policy is not ScreenshotPolicy.REQUIRED:
        return True
    changes = zip(
        output.change_ids,
        (split_change_evidence_refs(value) for value in output.change_evidence_refs),
        strict=True,
    )
    return has_publishable_screenshot_for_changes(deps.evidence, changes)


def release_notes_candidate_screenshot_available(deps: EvidenceAgentDeps) -> bool:
    return has_publishable_screenshot_for_changes(
        deps.evidence,
        ((change_id, ()) for change_id in deps.screenshot_candidate_change_ids),
    )


def release_notes_knowledge_context_issue(
    output: DocumentationUpdateModelOutput,
    deps: EvidenceAgentDeps,
) -> str | None:
    cited_refs = {
        reference
        for reference in [
            *output.evidence_refs,
            *(
                reference
                for value in output.change_evidence_refs
                for reference in split_change_evidence_refs(value)
            ),
        ]
        if reference.startswith("knowledge:")
    }
    if not cited_refs:
        return None
    available_refs = {item.evidence_ref for item in deps.selected_knowledge}
    unavailable = sorted(cited_refs.difference(available_refs))
    if unavailable:
        return (
            "Knowledge evidence refs must come from the preselected context manifest. "
            f"Remove unavailable refs: {', '.join(unavailable)}."
        )
    unread = sorted(cited_refs.difference(deps.knowledge_read_refs))
    if unread:
        return (
            "Read each cited knowledge item with read_knowledge_context before relying on it. "
            f"Unread refs: {', '.join(unread)}."
        )
    return None


def release_notes_evidence_consistency_issue(
    output: DocumentationUpdateModelOutput,
    manifest: AnalysisArtifactManifest | None,
) -> str | None:
    if manifest is None:
        return None
    issues: list[str] = []
    artifacts_by_id = {artifact.id: artifact for artifact in manifest.artifacts}
    change_texts: list[str] = []
    moved_change_subjects: list[set[str]] = []
    for change_id, title, summary, detail, how_to, evidence_value in zip(
        output.change_ids,
        output.change_titles,
        output.change_summaries,
        output.change_user_facing_details,
        output.change_how_to_markdown,
        output.change_evidence_refs,
        strict=True,
    ):
        primary = artifacts_by_id.get(change_id)
        if primary is None:
            issues.append(
                "Every itemized change must use an exact primary id from the analysis manifest; "
                f"unknown change id: {change_id}."
            )
            continue
        evidence_refs = set(split_change_evidence_refs(evidence_value))
        related = [
            artifact
            for artifact in manifest.artifacts
            if artifact.id == primary.id
            or evidence_refs.intersection(artifact.digest.evidence_refs)
        ]
        related_text = " ".join(
            " ".join(
                [
                    artifact.digest.technical_summary,
                    artifact.digest.product_impact,
                    *artifact.digest.risk_notes,
                ]
            )
            for artifact in related
        ).casefold()
        change_text = " ".join([title, summary, detail, how_to]).casefold()
        change_texts.append(change_text)
        issues.extend(
            release_summary_evidence_issues(
                change_id,
                title,
                evidence_refs,
                manifest,
            )
        )
        broadens_closed_set = claims_unbounded_closed_set(change_text)
        if broadens_closed_set and any(
            marker in related_text
            for marker in ("built-in", "closed set", "enum", "hardcoded list", "registry")
        ):
            issues.append(
                "A reported change broadens a value constrained by a finite enum, registry, "
                "hardcoded list, or other closed set into arbitrary custom content. Rewrite it "
                "to describe only the bounded choices directly supported by the related "
                "analysis evidence."
            )
        reported_stems = {Path(artifact.path).stem.casefold() for artifact in related}
        same_stem_history = [
            artifact
            for artifact in manifest.artifacts
            if Path(artifact.path).stem.casefold() in reported_stems
        ]
        move_text = " ".join(
            " ".join(
                [
                    artifact.digest.technical_summary,
                    artifact.digest.product_impact,
                    *artifact.digest.risk_notes,
                ]
            )
            for artifact in same_stem_history
        ).casefold()
        same_stem_removal = any(
            artifact.id != primary.id
            and indicates_material_removal(artifact.digest.technical_summary)
            for artifact in same_stem_history
        )
        move_evidence = same_stem_removal or any(
            marker in move_text
            for marker in ("moved the logic", "no observable change", "pre-existing behavior")
        )
        if move_evidence and (
            contains_new_automation_claim(change_text)
            or contains_unproven_improvement_claim(change_text)
        ):
            issues.append(
                f"Change {change_id} ({title!r}) presents moved behavior as newly automatic or "
                "qualitatively improved while the manifest also contains move or removal "
                "evidence. Remove that unsupported claim from this change and from the report "
                "overview. Treat a move or reorganization as pre-existing unless direct evidence "
                "proves a new user capability; describe only the exact supported public contract "
                "or corrected behavior."
            )
        if move_evidence:
            moved_change_subjects.append(subject_tokens(f"{title} {summary}"))
        if missing_evidenced_example_fields(how_to, related_text):
            issues.append(
                "A new configuration example omits fields that the related analysis evidence "
                "lists as part of every object. Rewrite each new-format item with the complete "
                "evidenced object shape; do not publish a migration example that fails its own "
                "configuration contract."
            )
    issues.extend(report_level_consistency_issues(output, change_texts, moved_change_subjects))
    return " ".join(dict.fromkeys(issues)) or None


def report_level_consistency_issues(
    output: DocumentationUpdateModelOutput,
    change_texts: list[str],
    moved_change_subjects: list[set[str]],
) -> list[str]:
    text = " ".join(
        [
            output.title,
            output.summary,
            output.user_facing_change,
            output.proposed_update_markdown,
        ]
    ).casefold()
    issues: list[str] = []
    if contains_new_automation_claim(text) and not any(
        contains_automation_claim(change_text) for change_text in change_texts
    ):
        issues.append(
            "The report-level prose introduces a new automation claim that is absent from every "
            "itemized change. Keep the title, summary, user-facing overview, and proposed Markdown "
            "consistent with the evidence-scoped change entries."
        )
    if report_improves_moved_subject(text, moved_change_subjects):
        issues.append(
            "The report-level prose qualitatively improves a subject whose itemized evidence "
            "shows moved or reorganized behavior. Keep the overview consistent with the exact "
            "supported contract and do not reintroduce an unsupported improvement outside the "
            "change row."
        )
    return issues


def report_improves_moved_subject(text: str, moved_subjects: list[set[str]]) -> bool:
    return any(
        contains_unproven_improvement_claim(sentence)
        and any(subject_tokens(sentence).intersection(subjects) for subjects in moved_subjects)
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text)
    )


def contains_new_automation_claim(text: str) -> bool:
    normalized = text.casefold()
    if re.search(r"\bautomated\b", normalized):
        return True
    return contains_automation_claim(normalized) and bool(
        re.search(r"\b(?:are|is|new|now|will)\b", normalized)
    )


def contains_automation_claim(text: str) -> bool:
    return bool(re.search(r"\bautomat(?:ic|ically|ed)\b", text.casefold()))


def indicates_material_removal(summary: str) -> bool:
    normalized = summary.casefold()
    if any(
        marker in normalized
        for marker in (
            "deleted the file",
            "removed the component",
            "removed the existing logic",
            "removed the helper",
            "removed the implementation",
        )
    ):
        return True
    return any(
        int(count) >= 10
        for count in re.findall(r"\b(\d+) deletions?\b", normalized)
    )


def contains_unproven_improvement_claim(text: str) -> bool:
    normalized = text.casefold()
    return (
        "better" in normalized
        or "more consistent" in normalized
        or any(stem in normalized for stem in IMPROVEMENT_STEMS)
    )


def claims_unbounded_closed_set(text: str) -> bool:
    normalized = text.casefold()
    if any(marker in normalized for marker in ("any value", "beyond predefined")):
        return True
    match = re.search(
        r"\b(?:custom|arbitrary|any)(?:\s+[a-z0-9_-]+){0,2}\s+(?:icons?|values?)\b",
        normalized,
    )
    if match is None:
        return False
    bounded_description = match.group()
    return "built-in" not in bounded_description and "predefined" not in bounded_description


def is_release_summary_path(path: str) -> bool:
    name = re.sub(r"[\s_]+", "-", Path(path).name.casefold())
    return name.startswith(("changelog", "release-notes"))


def release_summary_evidence_issues(
    change_id: str,
    title: str,
    evidence_refs: set[str],
    manifest: AnalysisArtifactManifest,
) -> list[str]:
    cited_artifacts = [
        artifact
        for artifact in manifest.artifacts
        if evidence_refs.intersection(artifact.digest.evidence_refs)
    ]
    if not cited_artifacts or any(
        not is_release_summary_path(artifact.path) for artifact in cited_artifacts
    ):
        return []
    return [
        f"Change {change_id} ({title!r}) cites only a changelog or release-notes summary. "
        "Cite direct implementation, configuration, documentation, or UI evidence for the "
        "claim, or omit this change; a release summary cannot independently substantiate "
        "another release report."
    ]


def release_notes_language_issue(
    output: DocumentationUpdateModelOutput,
    locale: str,
) -> str | None:
    if locale.casefold() != "en":
        return None
    user_facing_text = " ".join(
        [
            output.title,
            output.summary,
            output.user_facing_change,
            output.proposed_update_markdown,
            *output.risks_or_limitations,
            *output.suggested_improvements,
            *output.change_titles,
            *output.change_summaries,
            *output.change_user_facing_details,
            *output.change_how_to_markdown,
        ]
    )
    if re.search(r"[\u0400-\u04ff]", user_facing_text) is None:
        return None
    return (
        "Every user-facing report field must be written in English. Remove Cyrillic report "
        "prose while preserving exact English product labels and code identifiers."
    )


def subject_tokens(text: str) -> set[str]:
    ignored = {
        "and",
        "better",
        "change",
        "changes",
        "consistent",
        "enhanced",
        "improved",
        "management",
        "more",
        "optimized",
        "refined",
        "release",
        "support",
        "the",
        "update",
        "updated",
        "users",
        "with",
    }
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9_-]{2,}", text.casefold())
        if token not in ignored
        and not any(token.startswith(stem) for stem in IMPROVEMENT_STEMS)
    }


def missing_evidenced_example_fields(how_to: str, related_text: str) -> bool:
    field_groups = re.findall(
        r"array of objects (?:containing|with) ([^.]+)",
        related_text,
        flags=re.IGNORECASE,
    )
    required_fields = {
        field
        for group in field_groups
        for field in re.findall(r"`([A-Za-z_][A-Za-z0-9_-]*)`", group)
    }
    if len(required_fields) < 2:
        return False
    for object_body in re.findall(r"\{([^{}]+)\}", how_to, flags=re.DOTALL):
        present_fields = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_-]*)\s*:", object_body))
        if present_fields.intersection(required_fields) and not required_fields.issubset(
            present_fields
        ):
            return True
    return False
