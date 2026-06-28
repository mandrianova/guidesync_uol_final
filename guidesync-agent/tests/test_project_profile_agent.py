from __future__ import annotations

from pathlib import Path

from project_profile_fake_agent import FakeProjectProfileAgentProvider

from guidesync_agent.agent_runtime.context_compaction import ContextCompactionService
from guidesync_agent.agent_runtime.project_profile import (
    ProjectProfileRepositoryData,
    pydantic_project_profile_prompt,
    run_project_profile_agent,
)
from guidesync_agent.schemas import (
    AgentLoopObservation,
    AgentLoopRequest,
    AgentLoopToolCall,
    AgentLoopToolName,
    Audience,
    ProjectConfig,
    ProjectProfileAgentEvidence,
    ProjectProfileAgentOutput,
    ProjectProfileAgentRequest,
    ProjectProfileBuildReason,
    ProjectProfileEvidenceRef,
    ProjectProfileFileListing,
    ProjectProfileFileRef,
    ProjectProfileRepositoryMapItem,
    ProjectProfileRepositorySummary,
    ProjectProfileSnapshot,
    ProjectProfileSourceRef,
    ProjectTaxonomy,
    ProjectTaxonomyEvidenceKind,
    ProjectTaxonomyEvidenceRef,
    RepositoryCacheStatus,
    RepositoryFilesystemResult,
    RepositoryFileWindow,
    RepositorySearchMatch,
    RepositorySearchResult,
    ToolPagination,
)
from guidesync_agent.services.project_profile_evidence_normalization import (
    canonicalize_project_profile_output,
)
from guidesync_agent.services.project_profile_validation import validate_project_profile_output
from guidesync_agent.tools.project_profile_agent import (
    execute_project_profile_tool,
    initial_project_profile_observations,
    project_profile_tool_descriptors,
)


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
                    evidence_refs=["/repositories/repo-primary/docs/billing.md"],
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
                        evidence_ref="/repositories/repo-primary/docs/billing.md",
                    )
                ],
                pagination=ToolPagination(offset=0, limit=10, total=1),
            )
        ]
    )

    findings = validate_project_profile_output(output, evidence)

    assert not [finding for finding in findings if finding.severity == "error"]


def test_project_profile_output_canonicalizes_model_evidence_paths() -> None:
    evidence = ProjectProfileAgentEvidence(
        file_listings=[
            ProjectProfileFileListing(
                project_id="project-smoke",
                repository_id="smoke-fixture",
                files=[
                    ProjectProfileFileRef(
                        repository_id="smoke-fixture",
                        path="docs/guide.md",
                        evidence_ref="/repositories/smoke-fixture/docs/guide.md",
                    ),
                    ProjectProfileFileRef(
                        repository_id="smoke-fixture",
                        path="src/app.py",
                        evidence_ref="/repositories/smoke-fixture/src/app.py",
                    ),
                ],
                pagination=ToolPagination(offset=0, limit=10, total=2),
            )
        ],
        file_windows=[
            RepositoryFileWindow(
                repository_id="smoke-fixture",
                path="docs/guide.md",
                content="GuideSync local stack smoke test documentation.",
                pagination=ToolPagination(offset=0, limit=1000, total=52),
            ),
            RepositoryFileWindow(
                repository_id="smoke-fixture",
                path="src/app.py",
                content="def validate_tool(): return 'validation tool'",
                pagination=ToolPagination(offset=0, limit=1000, total=40),
            ),
        ],
    )
    output = ProjectProfileAgentOutput(
        summary="Smoke fixture profile.",
        project_description="GuideSync smoke fixture.",
        project_structure=["docs/guide.md documents the smoke workflow."],
        architecture=["src/app.py implements the validation tool."],
        core_concepts=["GuideSync", "local stack", "smoke test"],
        workflows=["smoke test"],
        agent_context="Use docs/guide.md and src/app.py as smoke fixture evidence.",
        profile_evidence=[
            ProjectProfileEvidenceRef(path="docs/guide.md", reason="documentation"),
            ProjectProfileEvidenceRef(path="src/app.py", reason="source"),
        ],
        taxonomy=ProjectTaxonomy(
            categories=["smoke test fixture", "validation tool"],
            components=["src/app.py (smoke test script)"],
            workflows=["local stack validation", "smoke test"],
            documentation_areas=["smoke guide (docs/guide.md)"],
            domain_terms=["GuideSync", "local stack"],
            evidence_refs=[
                ProjectTaxonomyEvidenceRef(
                    kind=ProjectTaxonomyEvidenceKind.COMPONENT,
                    value="src/app.py (smoke test script)",
                    evidence_refs=["src/app.py"],
                )
            ],
        ),
    )

    normalized = canonicalize_project_profile_output(output, evidence)
    findings = validate_project_profile_output(normalized, evidence)

    assert normalized.profile_evidence[0].repository_id == "smoke-fixture"
    assert {
        item.path for item in normalized.profile_evidence
    } == {"docs/guide.md", "src/app.py"}
    assert {
        ref
        for item in normalized.taxonomy.evidence_refs
        for ref in item.evidence_refs
    } >= {
        "/repositories/smoke-fixture/docs/guide.md",
        "/repositories/smoke-fixture/src/app.py",
    }
    assert normalized.taxonomy.evidence_refs
    assert not [finding for finding in findings if finding.severity == "error"]


def test_project_profile_validation_accepts_search_line_evidence_refs() -> None:
    output = ProjectProfileAgentOutput(
        summary="Profile summary",
        project_description="Search-backed documentation project.",
        project_structure=["docs/billing.md covers billing"],
        core_concepts=["billing"],
        agent_context="Billing docs context.",
        profile_evidence=[
            ProjectProfileEvidenceRef(
                repository_id="repo-primary",
                path="/repositories/repo-primary/docs/billing.md",
                reason="search result",
            )
        ],
        taxonomy=ProjectTaxonomy(
            categories=["billing"],
            evidence_refs=[
                ProjectTaxonomyEvidenceRef(
                    kind=ProjectTaxonomyEvidenceKind.CATEGORY,
                    value="billing",
                    evidence_refs=["/repositories/repo-primary/docs/billing.md#L12"],
                )
            ],
        ),
    )
    evidence = ProjectProfileAgentEvidence(
        search_results=[
            RepositorySearchResult(
                query="billing",
                matches=[
                    RepositorySearchMatch(
                        repository_id="repo-primary",
                        path="docs/billing.md",
                        line_number=12,
                        preview="Billing guide",
                    )
                ],
                total=1,
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
    assert "list_allowed_directories" in trace_names
    assert "list_directory" in trace_names
    assert "read_text_file" in trace_names
    assert result.selection.files_to_read
    assert result.output.agent_context
    assert result.model_metadata["agent_loop"] == "free_tool_loop"


def test_project_profile_descriptors_expose_repository_filesystem_tools() -> None:
    descriptors = project_profile_tool_descriptors()
    descriptor_names = {descriptor.name for descriptor in descriptors}
    descriptions = {descriptor.name: descriptor.description for descriptor in descriptors}

    assert AgentLoopToolName.LIST_ALLOWED_DIRECTORIES in descriptor_names
    assert AgentLoopToolName.LIST_DIRECTORY in descriptor_names
    assert AgentLoopToolName.DIRECTORY_TREE in descriptor_names
    assert AgentLoopToolName.SEARCH_FILES in descriptor_names
    assert AgentLoopToolName.READ_TEXT_FILE in descriptor_names
    assert AgentLoopToolName.READ_MULTIPLE_FILES in descriptor_names
    assert AgentLoopToolName.GET_FILE_INFO in descriptor_names
    assert "Grep-like" in descriptions[AgentLoopToolName.SEARCH_FILES]
    assert "path:line: preview" in descriptions[AgentLoopToolName.SEARCH_FILES]
    assert "list_repository_files" not in {name.value for name in descriptor_names}
    assert "read_repository_file" not in {name.value for name in descriptor_names}


def test_pydantic_project_profile_prompt_uses_typed_context_not_loop_protocol() -> None:
    request = ProjectProfileAgentRequest(
        project_id="project-prompt",
        profile_id="profile-prompt",
        reason=ProjectProfileBuildReason.TEST,
        name="Prompt project",
        audience=Audience.DEVELOPERS,
        repositories=[
            ProjectProfileRepositorySummary(
                project_id="project-prompt",
                repository_id="repo-prompt",
                name="fixture",
                url="/tmp/fixture",
                cache_status=RepositoryCacheStatus.READY,
            )
        ],
    )
    observations = [
        AgentLoopObservation(
            tool_name=AgentLoopToolName.LIST_ALLOWED_DIRECTORIES,
            output_summary="1 repository root available",
            payload={"roots": ["/repositories/repo-prompt/"]},
        )
    ]

    prompt = pydantic_project_profile_prompt(request, observations)

    assert '"project":' in prompt
    assert '"initial_observations":' in prompt
    assert "registered Pydantic AI repository tools" in prompt
    assert "arrays of strings" in prompt
    assert "tool_descriptors" not in prompt
    assert "action_contract" not in prompt
    assert "AgentLoopRequest" not in prompt


def test_project_profile_file_listing_is_bounded_for_large_repositories(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    for index in range(1200):
        (repository_root / f"file-{index:04}-long-fixture-name.md").write_text(
            f"# File {index}\n",
            encoding="utf-8",
        )
    request = ProjectProfileAgentRequest(
        project_id="project-large",
        profile_id="profile-large",
        reason=ProjectProfileBuildReason.TEST,
        name="Large project",
        audience=Audience.DEVELOPERS,
        repositories=[
            ProjectProfileRepositorySummary(
                project_id="project-large",
                repository_id="repo-large",
                name="fixture",
                url=str(repository_root),
                cache_status=RepositoryCacheStatus.READY,
                local_path=str(repository_root),
            )
        ],
    )

    default_observation = execute_project_profile_tool(
        request,
        AgentLoopToolCall(
            tool_name=AgentLoopToolName.LIST_DIRECTORY,
            arguments={"path": "/repositories/repo-large/"},
        ),
    )

    listing = RepositoryFilesystemResult.model_validate(default_observation.payload)
    assert listing.truncated is True
    assert "[FILE] file-0000-long-fixture-name.md" in listing.content
    assert "Narrow the path" in listing.content


def test_project_profile_file_listing_returns_first_level_tree(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    (repository_root / "docs").mkdir(parents=True)
    (repository_root / "packages" / "server" / "src").mkdir(parents=True)
    (repository_root / "README.md").write_text("# Project\n", encoding="utf-8")
    (repository_root / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (repository_root / "packages" / "package.json").write_text("{}", encoding="utf-8")
    (repository_root / "packages" / "server" / "src" / "index.ts").write_text(
        "export const server = true;\n",
        encoding="utf-8",
    )
    request = ProjectProfileAgentRequest(
        project_id="project-tree",
        profile_id="profile-tree",
        reason=ProjectProfileBuildReason.TEST,
        name="Tree project",
        audience=Audience.DEVELOPERS,
        repositories=[
            ProjectProfileRepositorySummary(
                project_id="project-tree",
                repository_id="repo-tree",
                name="fixture",
                url=str(repository_root),
                cache_status=RepositoryCacheStatus.READY,
                local_path=str(repository_root),
            )
        ],
    )

    root_observation = execute_project_profile_tool(
        request,
        AgentLoopToolCall(
            tool_name=AgentLoopToolName.LIST_DIRECTORY,
            arguments={"path": "/repositories/repo-tree/"},
        ),
    )
    packages_observation = execute_project_profile_tool(
        request,
        AgentLoopToolCall(
            tool_name=AgentLoopToolName.LIST_DIRECTORY,
            arguments={"path": "/repositories/repo-tree/packages"},
        ),
    )

    root_listing = RepositoryFilesystemResult.model_validate(root_observation.payload)
    packages_listing = RepositoryFilesystemResult.model_validate(packages_observation.payload)
    assert root_listing.path == "/repositories/repo-tree/"
    assert "[DIR] docs" in root_listing.content
    assert "[DIR] packages" in root_listing.content
    assert "[FILE] README.md" in root_listing.content
    assert "packages/server/src/index.ts" not in root_listing.content
    assert root_observation.output_summary.startswith("3 direct entries")
    assert packages_listing.path == "/repositories/repo-tree/packages"
    assert "[DIR] server" in packages_listing.content
    assert "[FILE] package.json" in packages_listing.content


def test_project_profile_initial_context_lists_virtual_roots(tmp_path: Path) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    request = ProjectProfileAgentRequest(
        project_id="project-roots",
        profile_id="profile-roots",
        reason=ProjectProfileBuildReason.TEST,
        name="Roots project",
        audience=Audience.DEVELOPERS,
        repositories=[
            ProjectProfileRepositorySummary(
                project_id="project-roots",
                repository_id="repo-roots",
                name="fixture",
                url=str(repository_root),
                cache_status=RepositoryCacheStatus.READY,
                local_path=str(repository_root),
            )
        ],
    )

    observations = initial_project_profile_observations(request)

    assert len(observations) == 1
    assert observations[0].tool_name == AgentLoopToolName.LIST_ALLOWED_DIRECTORIES
    assert "/repositories/repo-roots/" in observations[0].payload["content"]


def test_context_compaction_creates_checkpoint() -> None:
    loop_request = AgentLoopRequest(
        task_name="test_profile_loop",
        task_goal="test compaction",
        project_id="project-loop",
    )
    observations = [
        AgentLoopObservation(
            tool_name=AgentLoopToolName.READ_TEXT_FILE,
            output_summary=f"observation {index}",
            payload={"content": "x" * 500},
            evidence_refs=[f"/repositories/test/file-{index}.md"],
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
