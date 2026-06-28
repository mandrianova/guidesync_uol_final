from __future__ import annotations

from guidesync_agent.repository_evidence_refs import (
    canonical_repository_evidence_ref,
    repository_evidence_ref,
)
from guidesync_agent.schemas import (
    ProjectProfileAgentEvidence,
    ProjectProfileAgentOutput,
    ProjectProfileEvidenceRef,
    ProjectTaxonomyEvidenceKind,
    ValidationFinding,
)

DEFAULT_GENERIC_CATEGORIES = {
    "api",
    "auth",
    "billing",
    "docs",
    "release-notes",
    "settings",
    "ui-workflow",
    "user-management",
    "workspace",
}


def validate_project_profile_output(
    output: ProjectProfileAgentOutput,
    evidence: ProjectProfileAgentEvidence,
) -> list[ValidationFinding]:
    allowed_refs = allowed_evidence_refs(evidence)
    findings: list[ValidationFinding] = []
    if not output.summary.strip():
        findings.append(profile_error("summary is required", allowed_refs))
    if not output.project_description.strip():
        findings.append(profile_error("project_description is required", allowed_refs))
    if not output.agent_context.strip():
        findings.append(profile_error("agent_context is required", allowed_refs))
    if not output.project_structure and not output.uncertainty_notes:
        findings.append(
            profile_error(
                "project_structure is required unless uncertainty_notes explain the gap",
                allowed_refs,
            )
        )
    if not output.core_concepts and not output.uncertainty_notes:
        findings.append(
            profile_error(
                "core_concepts are required unless uncertainty_notes explain the gap",
                allowed_refs,
            )
        )
    if not output.profile_evidence:
        findings.append(profile_error("profile_evidence is required", allowed_refs))
    if not output.taxonomy.categories and not output.uncertainty_notes:
        findings.append(
            profile_error(
                "taxonomy.categories are required unless uncertainty_notes explain the gap",
                allowed_refs,
            )
        )
    findings.extend(validate_profile_evidence(output.profile_evidence, allowed_refs))
    findings.extend(validate_taxonomy_evidence(output, allowed_refs))
    return findings


def validate_profile_evidence(
    evidence_refs: list[ProjectProfileEvidenceRef],
    allowed_refs: set[str],
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for ref in evidence_refs:
        source = canonical_repository_evidence_ref(ref.path, ref.repository_id) or ref.path
        if source not in allowed_refs:
            findings.append(
                ValidationFinding(
                    severity="error",
                    check="project-profile.evidence",
                    message=f"Profile referenced unavailable evidence path: {source}",
                    evidence_refs=[source],
                )
            )
    return findings


def validate_taxonomy_evidence(
    output: ProjectProfileAgentOutput,
    allowed_refs: set[str],
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    evidence_by_key = {
        (item.kind, normalize(item.value)): item.evidence_refs
        for item in output.taxonomy.evidence_refs
    }
    required_values = [
        (ProjectTaxonomyEvidenceKind.CATEGORY, value) for value in output.taxonomy.categories
    ]
    required_values.extend(
        (ProjectTaxonomyEvidenceKind.COMPONENT, value) for value in output.taxonomy.components
    )
    required_values.extend(
        (ProjectTaxonomyEvidenceKind.WORKFLOW, value) for value in output.taxonomy.workflows
    )
    required_values.extend(
        (ProjectTaxonomyEvidenceKind.DOCUMENTATION_AREA, value)
        for value in output.taxonomy.documentation_areas
    )
    required_values.extend(
        (ProjectTaxonomyEvidenceKind.DOMAIN_TERM, value) for value in output.taxonomy.domain_terms
    )
    for kind, value in required_values:
        refs = evidence_by_key.get((kind, normalize(value)), [])
        if not refs:
            findings.append(missing_taxonomy_evidence(kind, value))
            continue
        unknown_refs = [
            canonical_ref or ref
            for ref in refs
            if (canonical_ref := canonical_repository_evidence_ref(ref)) not in allowed_refs
        ]
        if unknown_refs:
            findings.append(
                ValidationFinding(
                    severity="error",
                    check="project-profile.taxonomy-evidence",
                    message=f"Taxonomy value '{value}' uses unavailable evidence refs.",
                    evidence_refs=unknown_refs,
                )
            )
    for category in output.taxonomy.categories:
        if normalize(category) in DEFAULT_GENERIC_CATEGORIES:
            refs = evidence_by_key.get(
                (ProjectTaxonomyEvidenceKind.CATEGORY, normalize(category)),
                [],
            )
            if not refs:
                findings.append(
                    ValidationFinding(
                        severity="error",
                        check="project-profile.generic-category",
                        message=(
                            f"Generic category '{category}' cannot be selected without "
                            "repository evidence."
                        ),
                    )
                )
    return findings


def allowed_evidence_refs(evidence: ProjectProfileAgentEvidence) -> set[str]:
    refs: set[str] = set()
    for listing in evidence.file_listings:
        for directory in listing.directories:
            refs.add(
                canonical_repository_evidence_ref(
                    directory.evidence_ref,
                    directory.repository_id,
                )
                or repository_evidence_ref(
                    directory.repository_id,
                    directory.path,
                    is_directory=True,
                )
            )
        for file in listing.files:
            refs.add(
                canonical_repository_evidence_ref(file.evidence_ref, file.repository_id)
                or repository_evidence_ref(file.repository_id, file.path)
            )
    for window in evidence.file_windows:
        refs.add(repository_evidence_ref(window.repository_id, window.path))
    for result in evidence.search_results:
        for match in result.matches:
            refs.add(repository_evidence_ref(match.repository_id, match.path))
            refs.add(
                repository_evidence_ref(
                    match.repository_id,
                    match.path,
                    line_number=match.line_number,
                )
            )
    return refs


def profile_error(message: str, evidence_refs: set[str]) -> ValidationFinding:
    return ValidationFinding(
        severity="error",
        check="project-profile.output",
        message=message,
        evidence_refs=sorted(evidence_refs)[:40],
    )


def missing_taxonomy_evidence(
    kind: ProjectTaxonomyEvidenceKind,
    value: str,
) -> ValidationFinding:
    return ValidationFinding(
        severity="error",
        check="project-profile.taxonomy-evidence",
        message=f"Taxonomy {kind.value} '{value}' must include repository evidence refs.",
    )


def has_blocking_findings(findings: list[ValidationFinding]) -> bool:
    return any(finding.severity == "error" for finding in findings)


def normalize(value: str) -> str:
    return value.strip().lower()
