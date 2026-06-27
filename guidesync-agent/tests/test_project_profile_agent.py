from __future__ import annotations

from pathlib import Path

from guidesync_agent.schemas import (
    AgentLoopObservation,
    AgentLoopRequest,
    AgentLoopToolName,
    ProjectConfig,
    ProjectProfileAgentEvidence,
    ProjectProfileAgentOutput,
    ProjectProfileEvidenceRef,
    ProjectProfileFileListing,
    ProjectProfileFileRef,
    ProjectProfileRepositoryMapItem,
    ProjectProfileSnapshot,
    ProjectProfileSourceRef,
    ProjectTaxonomy,
    ProjectTaxonomyEvidenceKind,
    ProjectTaxonomyEvidenceRef,
    RepositoryCacheStatus,
    ToolPagination,
)
from guidesync_agent.services.context_compaction import ContextCompactionService
from guidesync_agent.services.project_profile_agent import (
    ProjectProfileRepositoryData,
    run_project_profile_agent,
)
from guidesync_agent.services.project_profile_fake_agent import FakeProjectProfileAgentProvider
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


def test_project_profile_agent_uses_free_loop_tools(tmp_path: Path) -> None:
    repository_root = tmp_path / "repo"
    (repository_root / "docs").mkdir(parents=True)
    (repository_root / "src").mkdir()
    (repository_root / "README.md").write_text(
        "# GuideSync Loop Project\n\nRelease review workflow and knowledge base docs.\n",
        encoding="utf-8",
    )
    (repository_root / "src" / "AppShell.tsx").write_text(
        "export function AppShell() { return 'release notes'; }\n",
        encoding="utf-8",
    )
    project = ProjectConfig(
        id="project-loop",
        name="Loop project",
        description="Project profile loop test.",
        analysis_paths=["."],
    )
    base_profile = ProjectProfileSnapshot(
        project_id=project.id,
        prompt_version="test-profile",
    )
    repository_map = ProjectProfileRepositoryMapItem(
        repository_id="repo-loop",
        name="fixture",
        url=str(repository_root),
        default_branch="main",
        cache_status=RepositoryCacheStatus.READY,
        analysis_paths=["."],
        knowledge_base_path="docs/",
    )
    source_ref = ProjectProfileSourceRef(
        repository_id="repo-loop",
        repository_name="fixture",
        ref="main",
        local_path=str(repository_root),
        docs_path="docs/",
        analysis_paths=["."],
    )

    result = run_project_profile_agent(
        project,
        base_profile,
        [ProjectProfileRepositoryData(repository_map, source_ref, [])],
        provider=FakeProjectProfileAgentProvider(),
        reason="test",
    )

    trace_names = [trace.tool_name for trace in result.evidence.tool_trace]
    assert "list_repository_files" in trace_names
    assert "read_repository_file" in trace_names
    assert result.selection.files_to_read
    assert result.output.agent_context
    assert result.model_metadata["agent_loop"] == "free_tool_loop"


def test_context_compaction_creates_checkpoint() -> None:
    loop_request = AgentLoopRequest(
        task_name="test_profile_loop",
        task_goal="test compaction",
        project_id="project-loop",
    )
    observations = [
        AgentLoopObservation(
            tool_name=AgentLoopToolName.READ_REPOSITORY_FILE,
            output_summary=f"observation {index}",
            payload={"content": "x" * 500},
            evidence_refs=[f"repo:test:file-{index}.md"],
        )
        for index in range(8)
    ]

    decision = ContextCompactionService(
        threshold_tokens=200,
        retain_recent_observations=2,
    ).prepare_prompt_observations(
        request=loop_request,
        observations=observations,
        checkpoint_count=0,
    )

    assert decision.checkpoint is not None
    assert len(decision.observations) == 2
    assert len(decision.checkpoint.summarized_observation_ids) == 6
