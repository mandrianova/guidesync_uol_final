from __future__ import annotations

from pathlib import Path

from guidesync_agent.agent_runtime.project_profile import (
    ProjectProfileAgentRunRequest,
    ProjectProfileRepositoryData,
    pydantic_project_profile_prompt,
    run_project_profile_agent,
)
from guidesync_agent.schemas import (
    AgentLoopObservation,
    AgentLoopToolCall,
    AgentLoopToolName,
    AgentToolResultStatus,
    Audience,
    ProjectConfig,
    ProjectProfileAgentEvidence,
    ProjectProfileAgentOutput,
    ProjectProfileAgentRequest,
    ProjectProfileBuildReason,
    ProjectProfileFileListing,
    ProjectProfileFileRef,
    ProjectProfileRepositoryMapItem,
    ProjectProfileRepositorySummary,
    ProjectProfileSnapshot,
    ProjectProfileSourceRef,
    RepositoryCacheStatus,
    RepositoryFilesystemResult,
    RepositoryFileWindow,
    RepositorySearchMatch,
    RepositorySearchResult,
    ToolPagination,
)
from guidesync_agent.services.project_profile.evidence_normalization import (
    canonicalize_project_profile_output,
)
from guidesync_agent.services.project_profile.validation import validate_project_profile_output
from guidesync_agent.tools.policy import execute_with_policy
from guidesync_agent.tools.project_profile_agent import (
    execute_project_profile_tool,
    initial_project_profile_observations,
    project_profile_evidence_from_observations,
    project_profile_tool_descriptors,
    register_project_profile_agent_tools,
)
from guidesync_agent.tools.registry import agent_loop_tool_definition


def test_project_profile_validation_rejects_incomplete_output() -> None:
    output = ProjectProfileAgentOutput(
        summary="Profile summary",
    )

    findings = validate_project_profile_output(output, ProjectProfileAgentEvidence())

    assert {finding.message for finding in findings} >= {
        "project_description is required",
        "project_structure is required",
        "architecture is required",
        "core_concepts are required",
        "categories are required",
    }


def test_project_profile_validation_accepts_repository_evidence() -> None:
    output = ProjectProfileAgentOutput(
        summary="Profile summary",
        project_description="Billing documentation project.",
        project_structure="- docs/: billing guide",
        architecture="- FastAPI backend\n- React frontend",
        core_concepts=["billing"],
        categories=["billing"],
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


def test_project_profile_output_canonicalizes_text_and_lists() -> None:
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
        summary="  Smoke   fixture profile.  ",
        project_description="GuideSync   smoke fixture.",
        project_structure="  - docs/guide.md documents the smoke workflow.\n\n  ",
        architecture=" - src/app.py implements the validation tool.  ",
        core_concepts=["GuideSync", "GuideSync", "local stack", "smoke test"],
        categories=["smoke test fixture", "validation tool", "validation tool"],
    )

    normalized = canonicalize_project_profile_output(output, evidence)
    findings = validate_project_profile_output(normalized, evidence)

    assert normalized.summary == "Smoke fixture profile."
    assert normalized.project_structure == "- docs/guide.md documents the smoke workflow."
    assert normalized.core_concepts == ["GuideSync", "local stack", "smoke test"]
    assert normalized.categories == ["smoke test fixture", "validation tool"]
    assert not [finding for finding in findings if finding.severity == "error"]


def test_project_profile_validation_accepts_search_line_evidence_refs() -> None:
    output = ProjectProfileAgentOutput(
        summary="Profile summary",
        project_description="Search-backed documentation project.",
        project_structure="- docs/billing.md covers billing",
        architecture="- Search-backed profile",
        core_concepts=["billing"],
        categories=["billing"],
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
        ProjectProfileAgentRunRequest(
            project=project,
            base_profile=base_profile,
            repository_data=[ProjectProfileRepositoryData(repository_map, source_ref, [])],
            reason="test",
        )
    )

    trace_names = [trace.tool_name for trace in result.evidence.tool_trace]
    assert "list_allowed_directories" in trace_names
    assert "list_directory" in trace_names
    assert "read_text_file" in trace_names
    assert result.selection.files_to_read
    assert result.output.categories
    assert result.output.project_structure
    assert result.output.architecture
    assert result.model_metadata["agent_runtime"] == "pydantic_ai"


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


def test_project_profile_agent_tools_register_with_pydantic_ai() -> None:
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    agent = Agent(TestModel(), output_type=str)

    register_project_profile_agent_tools(agent)


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
    normalized_prompt = " ".join(prompt.split())

    assert '"project":' in prompt
    assert '"initial_observations":' in prompt
    assert "read-only repository tools" in prompt
    assert "Markdown string fields" in prompt
    assert "documentation content areas" in normalized_prompt
    assert "ProjectTaxonomy" not in prompt
    assert "Pydantic AI" not in prompt
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


def test_project_profile_accepts_policy_truncated_filesystem_observation(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    (repository_root / "README.md").write_text("# Project\n", encoding="utf-8")
    request = ProjectProfileAgentRequest(
        project_id="project-truncated",
        profile_id="profile-truncated",
        reason=ProjectProfileBuildReason.TEST,
        name="Truncated project",
        audience=Audience.DEVELOPERS,
        repositories=[
            ProjectProfileRepositorySummary(
                project_id="project-truncated",
                repository_id="repo-truncated",
                name="fixture",
                url=str(repository_root),
                cache_status=RepositoryCacheStatus.READY,
                local_path=str(repository_root),
            )
        ],
    )
    call = AgentLoopToolCall(
        tool_name=AgentLoopToolName.LIST_DIRECTORY,
        arguments={"path": "/repositories/repo-truncated/"},
    )
    definition = agent_loop_tool_definition(call.tool_name).model_copy(
        update={"max_output_chars": 10}
    )

    observation = execute_with_policy(
        call,
        {call.tool_name: definition},
        lambda _: execute_project_profile_tool(request, call),
    )
    evidence = project_profile_evidence_from_observations(request, [observation])

    assert observation.result_status is AgentToolResultStatus.TRUNCATED
    assert observation.payload["tool_name"] == AgentLoopToolName.LIST_DIRECTORY.value
    assert evidence.file_listings[0].pagination.truncated is True
    assert evidence.file_listings[0].files == []


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
