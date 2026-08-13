from __future__ import annotations

from guidesync_agent.schemas import (
    ProjectProfileAgentEvidence,
    ProjectProfileAgentOutput,
    ValidationFinding,
)


def validate_project_profile_output(
    output: ProjectProfileAgentOutput,
    evidence: ProjectProfileAgentEvidence,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    if not output.summary.strip():
        findings.append(profile_error("summary is required", evidence))
    if not output.project_description.strip():
        findings.append(profile_error("project_description is required", evidence))
    if not output.project_structure.strip():
        findings.append(profile_error("project_structure is required", evidence))
    if not output.architecture.strip():
        findings.append(profile_error("architecture is required", evidence))
    if not output.core_concepts:
        findings.append(profile_error("core_concepts are required", evidence))
    if not output.categories:
        findings.append(profile_error("categories are required", evidence))
    if len(output.categories) > 12:
        findings.append(profile_error("categories must stay to 12 or fewer items", evidence))
    return findings


def output_evidence_refs(evidence: ProjectProfileAgentEvidence) -> list[str]:
    refs: set[str] = set()
    for listing in evidence.file_listings:
        for directory in listing.directories:
            refs.add(directory.evidence_ref)
        for file in listing.files:
            refs.add(file.evidence_ref)
    for window in evidence.file_windows:
        refs.add(f"/repositories/{window.repository_id}/{window.path}")
    for result in evidence.search_results:
        for match in result.matches:
            refs.add(f"/repositories/{match.repository_id}/{match.path}")
    return sorted(refs)[:40]


def profile_error(message: str, evidence: ProjectProfileAgentEvidence) -> ValidationFinding:
    return ValidationFinding(
        severity="error",
        check="project-profile.output",
        message=message,
        evidence_refs=output_evidence_refs(evidence),
    )


def has_blocking_findings(findings: list[ValidationFinding]) -> bool:
    return any(finding.severity == "error" for finding in findings)
