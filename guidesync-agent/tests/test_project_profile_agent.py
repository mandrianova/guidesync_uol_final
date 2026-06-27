from __future__ import annotations

from guidesync_agent.schemas import (
    ProjectProfileAgentEvidence,
    ProjectProfileAgentOutput,
    ProjectProfileEvidenceRef,
    ProjectProfileFileListing,
    ProjectProfileFileRef,
    ProjectTaxonomy,
    ProjectTaxonomyEvidenceKind,
    ProjectTaxonomyEvidenceRef,
    ToolPagination,
)
from guidesync_agent.services.project_profile_validation import validate_project_profile_output


def test_project_profile_validation_rejects_taxonomy_without_evidence() -> None:
    output = ProjectProfileAgentOutput(
        summary="Profile summary",
        taxonomy=ProjectTaxonomy(categories=["billing"]),
    )

    findings = validate_project_profile_output(output, ProjectProfileAgentEvidence())

    assert any(finding.check == "project-profile.taxonomy-evidence" for finding in findings)
    assert any(finding.check == "project-profile.generic-category" for finding in findings)


def test_project_profile_validation_accepts_repository_evidence() -> None:
    output = ProjectProfileAgentOutput(
        summary="Profile summary",
        project_description="Billing documentation project.",
        project_structure=["docs/: billing guide"],
        core_concepts=["billing"],
        agent_context="Billing documentation project context.",
        profile_evidence=[
            ProjectProfileEvidenceRef(
                repository_id="repo-primary",
                path="docs/billing.md",
                reason="docs",
            )
        ],
        taxonomy=ProjectTaxonomy(
            categories=["billing"],
            evidence_refs=[
                ProjectTaxonomyEvidenceRef(
                    kind=ProjectTaxonomyEvidenceKind.CATEGORY,
                    value="billing",
                    evidence_refs=["repo:repo-primary:docs/billing.md"],
                )
            ],
        ),
    )
    evidence = ProjectProfileAgentEvidence(
        file_listings=[
            ProjectProfileFileListing(
                project_id="project-1",
                repository_id="repo-primary",
                files=[
                    ProjectProfileFileRef(
                        repository_id="repo-primary",
                        path="docs/billing.md",
                        evidence_ref="repo:repo-primary:docs/billing.md",
                    )
                ],
                pagination=ToolPagination(offset=0, limit=10, total=1),
            )
        ]
    )

    findings = validate_project_profile_output(output, evidence)

    assert not [finding for finding in findings if finding.severity == "error"]
