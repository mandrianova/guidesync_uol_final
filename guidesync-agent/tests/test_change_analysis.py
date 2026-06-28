from __future__ import annotations

import subprocess
from pathlib import Path

from storage_test_utils import sqlite_database_url

from guidesync_agent.agent_runtime.code_change import (
    CodeChangeAnalysisEvidence,
    CodeChangeAnalysisRequest,
    analyze_code_change_with_subagent,
    code_change_analyzer_prompt,
    code_change_prompt,
    pydantic_code_change_prompt,
)
from guidesync_agent.agent_runtime.loop import run_agent_loop
from guidesync_agent.schemas import (
    AgentLoopActionType,
    AgentLoopModelAction,
    AgentLoopPromptContext,
    AgentLoopToolCall,
    AgentLoopToolName,
    ChangedFileRef,
    CodeChangeAnalysis,
    CodeChangeCandidateTaxonomyUpdate,
    CodeChangeEvidenceRef,
    CodeChangeTaxonomyMatch,
    FileChangeSummary,
    KnowledgeConceptKind,
    ModelRole,
    ProjectCreate,
    ProjectProfileSnapshot,
    ProjectRepository,
    ProjectTaxonomy,
    ProviderKind,
    TokenUsageSource,
)
from guidesync_agent.services.change_analysis import (
    summarize_changed_file,
    summarize_changed_files,
)
from guidesync_agent.storage import DatabaseModelUsageStore, DatabaseProjectStore
from guidesync_agent.tools.code_change_agent import (
    code_change_loop_request,
    code_change_tool_descriptors,
    execute_code_change_tool,
    initial_code_change_observations,
)


def run_git(repo: Path | None, args: list[str]) -> None:
    command = ["git", *args] if repo is None else ["git", "-C", str(repo), *args]
    subprocess.run(command, check=True, capture_output=True, text=True)


def create_source_repository(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "docs").mkdir(parents=True)
    (source / "src").mkdir()
    (source / "docs" / "guide.md").write_text(
        "# Guide\n\nInitial workflow documentation.\n",
        encoding="utf-8",
    )
    (source / "src" / "app.py").write_text("print('initial')\n", encoding="utf-8")
    run_git(None, ["init", str(source)])
    run_git(source, ["config", "user.email", "test@example.com"])
    run_git(source, ["config", "user.name", "GuideSync Test"])
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Initial docs"])
    (source / "docs" / "guide.md").write_text(
        "# Guide\n\nInitial workflow documentation.\n\nDocument per-file summaries.\n",
        encoding="utf-8",
    )
    (source / "src" / "app.py").write_text(
        "print('initial')\nprint('per-file summaries')\n",
        encoding="utf-8",
    )
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Update docs and app"])
    run_git(source, ["branch", "-M", "main"])
    return source


def create_project(monkeypatch, tmp_path: Path) -> tuple[str, str]:
    database_url = sqlite_database_url(tmp_path / "change-analysis.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "cache"))
    source = create_source_repository(tmp_path)
    project = DatabaseProjectStore(database_url).save(
        ProjectCreate(
            name="Change analysis project",
            repositories=[
                ProjectRepository(
                    id="repo-change-analysis",
                    name="fixture",
                    url=str(source),
                    default_branch="main",
                    analysis_paths=["docs", "src"],
                )
            ],
        )
    )
    return project.id, "repo-change-analysis"


def test_summarizer_creates_bounded_file_summaries(monkeypatch, tmp_path: Path) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)

    summaries = summarize_changed_files(
        project_id,
        repository_id,
        [
            ChangedFileRef(path="docs/guide.md", status="M"),
            ChangedFileRef(path="src/app.py", status="M"),
        ],
        goal="Document per-file summaries.",
        audience="developers",
    )

    assert {summary.path for summary in summaries} == {"docs/guide.md", "src/app.py"}
    assert all(summary.technical_summary for summary in summaries)
    assert all(summary.documentation_keywords for summary in summaries)
    assert any(
        summary.path == "src/app.py" and summary.needs_main_agent_review for summary in summaries
    )
    serialized = [summary.model_dump(mode="json") for summary in summaries]
    assert all("diff" not in item and "content" not in item for item in serialized)


def test_failed_file_summary_marks_review_without_failing_run(monkeypatch, tmp_path: Path) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)

    summary = summarize_changed_file(
        project_id,
        repository_id,
        ChangedFileRef(path="../outside.md", status="M"),
        goal="Document unsafe paths.",
        audience="developers",
    )

    assert summary.path == "../outside.md"
    assert summary.needs_main_agent_review is True
    assert summary.risk_notes
    assert any("path_outside_repository" in note for note in summary.risk_notes)
    assert summary.evidence_refs == [
        "diff-error:repo-change-analysis:../outside.md",
        "file-error:repo-change-analysis:../outside.md",
    ]
    assert summary.analysis_artifact is not None
    assert [ref.source for ref in summary.analysis_artifact.evidence_refs] == summary.evidence_refs


def test_llm_change_analysis_output_drives_structured_summary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)
    provider = FakeStructuredProvider()

    summary = summarize_changed_file(
        project_id,
        repository_id,
        ChangedFileRef(path="src/app.py", status="M"),
        goal="Document changed-file manifests.",
        audience="developers",
        project_profile=project_profile(project_id),
        analysis_provider=provider,
    )

    assert summary.analysis_provider == "fake"
    assert summary.analysis_model == "fake-structured"
    assert summary.what_changed == "AppShell now shows the changed-file manifest status."
    assert summary.affected_components == ["AppShell"]
    assert summary.affected_workflows == ["changed-file manifest"]
    assert summary.documentation_search_intents == ["changed-file manifest workflow"]
    assert [match.value for match in summary.taxonomy_matches] == ["AppShell"]
    assert any(update.value == "billing" for update in summary.candidate_taxonomy_updates)
    assert summary.annotation_run_id
    assert summary.analysis_artifact is not None
    assert summary.analysis_artifact.prompt_version == "docs-update-code-change-analyzer-v1"
    assert summary.analysis_artifact.evidence_refs
    assert any(
        finding.check == "code-change-analysis.taxonomy"
        for finding in summary.analysis_artifact.validation_findings
    )
    serialized = summary.model_dump(mode="json")
    assert "diff" not in serialized and "content" not in serialized


def test_invalid_llm_change_analysis_falls_back_to_deterministic_summary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)

    summary = summarize_changed_file(
        project_id,
        repository_id,
        ChangedFileRef(path="src/app.py", status="M"),
        goal="Document changed-file manifests.",
        audience="developers",
        project_profile=project_profile(project_id),
        analysis_provider=InvalidStructuredProvider(),
    )

    assert summary.analysis_provider == "deterministic"
    assert summary.analysis_model == "heuristic-fallback"
    assert summary.technical_summary
    assert summary.analysis_artifact is not None
    assert summary.analysis_artifact.provider == "deterministic"
    assert any("fell back to deterministic output" in note for note in summary.risk_notes)
    assert any(
        finding.check == "code-change-analysis.fallback"
        for finding in summary.analysis_artifact.validation_findings
    )


def test_code_change_prompt_uses_runtime_schema_metadata() -> None:
    request = CodeChangeAnalysisRequest(
        project_id="project-test",
        repository_id="repo-test",
        path="src/app.py",
        status="M",
        goal="Document app changes.",
        audience="developers",
        fallback_summary=FileChangeSummary(
            repository_id="repo-test",
            path="src/app.py",
            status="M",
            technical_summary="Fallback technical summary.",
            product_impact="Fallback product impact.",
        ),
        evidence=CodeChangeAnalysisEvidence(),
    )

    prompt = code_change_prompt(request)

    assert "expected_schema" not in prompt.user
    assert prompt.metadata["code_change_analysis_prompt_id"] == "docs_update.code_change_analyzer"
    assert prompt.metadata["code_change_analysis_prompt_version"]
    assert len(prompt.metadata["code_change_analysis_prompt_sha256"]) == 64


def test_pydantic_code_change_prompt_uses_typed_context_not_loop_protocol() -> None:
    request = CodeChangeAnalysisRequest(
        project_id="project-test",
        repository_id="repo-test",
        path="src/app.py",
        status="M",
        goal="Document app changes.",
        audience="developers",
        fallback_summary=FileChangeSummary(
            repository_id="repo-test",
            path="src/app.py",
            status="M",
            technical_summary="Fallback technical summary.",
            product_impact="Fallback product impact.",
        ),
        evidence=CodeChangeAnalysisEvidence(
            diff="+print('changed')",
            current_file="print('changed')\n",
            evidence_refs=[
                CodeChangeEvidenceRef(
                    source="diff:repo-test:src/app.py",
                    detail="initial raw diff",
                )
            ],
        ),
    )

    prompt = pydantic_code_change_prompt(
        request,
        code_change_analyzer_prompt(),
        initial_code_change_observations(request),
    )

    assert '"change":' in prompt
    assert '"initial_observations":' in prompt
    assert "available evidence tools" in prompt
    assert "kind and value fields" in prompt
    assert "Pydantic AI" not in prompt
    assert "tool_descriptors" not in prompt
    assert "action_contract" not in prompt
    assert "AgentLoopRequest" not in prompt


def test_code_change_descriptors_expose_filesystem_tools_and_separate_diff() -> None:
    names = {descriptor.name for descriptor in code_change_tool_descriptors()}

    assert AgentLoopToolName.READ_RAW_DIFF in names
    assert AgentLoopToolName.LIST_ALLOWED_DIRECTORIES in names
    assert AgentLoopToolName.LIST_DIRECTORY in names
    assert AgentLoopToolName.DIRECTORY_TREE in names
    assert AgentLoopToolName.SEARCH_FILES in names
    assert AgentLoopToolName.READ_TEXT_FILE in names
    assert AgentLoopToolName.READ_MULTIPLE_FILES in names
    assert AgentLoopToolName.GET_FILE_INFO in names
    assert "list_repository_files" not in {name.value for name in names}
    assert "read_repository_file" not in {name.value for name in names}


def test_code_change_subagent_records_model_usage(monkeypatch, tmp_path: Path) -> None:
    database_url = sqlite_database_url(tmp_path / "code-change-usage.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    evidence_ref = CodeChangeEvidenceRef(
        source="diff:repo-test:src/app.py",
        detail="raw diff inspected",
    )
    request = CodeChangeAnalysisRequest(
        run_id="run-code-change-1",
        workflow_task_id="workflow-code-change-1",
        project_id="project-test",
        repository_id="repo-test",
        path="src/app.py",
        status="M",
        goal="Document app changes.",
        audience="developers",
        fallback_summary=FileChangeSummary(
            repository_id="repo-test",
            path="src/app.py",
            status="M",
            technical_summary="Fallback technical summary.",
            product_impact="Fallback product impact.",
        ),
        evidence=CodeChangeAnalysisEvidence(evidence_refs=[evidence_ref]),
    )

    result = analyze_code_change_with_subagent(
        request,
        provider=UsageStructuredProvider(),
    )

    entries = DatabaseModelUsageStore(database_url).list_for_run("run-code-change-1")
    assert result.artifact.provider == ProviderKind.LOCAL_HTTP.value
    assert len(entries) == 1
    assert entries[0].role == ModelRole.CODE_CHANGE_ANALYSIS
    assert entries[0].workflow_task_id == "workflow-code-change-1"
    assert entries[0].provider == ProviderKind.LOCAL_HTTP
    assert entries[0].model == "openai:test-model"
    assert entries[0].endpoint_type == "openai_compatible"
    assert entries[0].base_url_host_hash == "hash-only"
    assert entries[0].usage_source == TokenUsageSource.PROVIDER_REPORTED
    assert entries[0].usage.input_tokens == 10
    assert entries[0].usage.output_tokens == 5
    assert entries[0].usage.provider_reported_total_tokens == 15
    assert entries[0].usage.model_turn_count == 2
    assert entries[0].usage.tool_call_count == 1


def test_code_change_loop_can_read_additional_repository_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)
    request = CodeChangeAnalysisRequest(
        project_id=project_id,
        repository_id=repository_id,
        path="src/app.py",
        status="M",
        goal="Document changed-file manifests.",
        audience="developers",
        fallback_summary=FileChangeSummary(
            repository_id=repository_id,
            path="src/app.py",
            status="M",
            technical_summary="Fallback technical summary.",
            product_impact="Fallback product impact.",
        ),
        evidence=CodeChangeAnalysisEvidence(
            diff="+print('per-file summaries')",
            current_file="print('initial')\nprint('per-file summaries')\n",
            evidence_refs=[
                CodeChangeEvidenceRef(
                    source=f"diff:{repository_id}:src/app.py",
                    detail="initial raw diff",
                ),
                CodeChangeEvidenceRef(
                    source=f"file:{repository_id}:src/app.py",
                    detail="initial current file",
                ),
            ],
        ),
        project_profile=project_profile(project_id),
    )

    result = run_agent_loop(
        request=code_change_loop_request(request, code_change_analyzer_prompt()),
        provider=FakeCodeChangeLoopProvider(),
        execute_tool=lambda call: execute_code_change_tool(request, call),
        final_output_model=CodeChangeAnalysis,
        initial_observations=initial_code_change_observations(request),
    )

    analysis = CodeChangeAnalysis.model_validate(result.final_output)
    assert analysis.technical_summary == "Loop inspected app and docs evidence."
    assert any(
        observation.tool_name == AgentLoopToolName.LIST_DIRECTORY
        for observation in result.observations
    )
    assert any(
        observation.tool_name == AgentLoopToolName.READ_TEXT_FILE
        and observation.payload.get("metadata", {}).get("relative_path") == "docs/guide.md"
        for observation in result.observations
    )


class FakeStructuredProvider:
    provider = "fake"
    model = "fake-structured"

    def analyze(self, request: CodeChangeAnalysisRequest) -> object:
        evidence_refs = [ref.source for ref in request.evidence.evidence_refs]
        return CodeChangeAnalysis(
            what_changed="AppShell now shows the changed-file manifest status.",
            technical_summary="Updated AppShell to expose changed-file manifest status.",
            user_or_product_impact=(
                "Developers can see when changed-file manifest data is available."
            ),
            affected_components=["AppShell"],
            affected_workflows=["changed-file manifest"],
            documentation_search_intents=["changed-file manifest workflow"],
            taxonomy_matches=[
                CodeChangeTaxonomyMatch(
                    kind=KnowledgeConceptKind.COMPONENT,
                    value="AppShell",
                    evidence_refs=evidence_refs,
                ),
                CodeChangeTaxonomyMatch(
                    kind=KnowledgeConceptKind.CATEGORY,
                    value="billing",
                    evidence_refs=evidence_refs,
                ),
            ],
            candidate_taxonomy_updates=[
                CodeChangeCandidateTaxonomyUpdate(
                    kind=KnowledgeConceptKind.CANDIDATE,
                    value="manifest status",
                    reason="New UI label in changed code.",
                    evidence_refs=evidence_refs,
                )
            ],
            key_terms_from_code=["AppShell", "changed-file manifest"],
            needs_screenshot_check=True,
            evidence_refs=evidence_refs,
        )


class InvalidStructuredProvider:
    provider = "fake"
    model = "invalid"

    def analyze(self, request: CodeChangeAnalysisRequest) -> object:
        return {"technical_summary": "", "documentation_search_intents": []}


class UsageStructuredProvider:
    provider = ProviderKind.LOCAL_HTTP.value
    model = "openai:test-model"
    last_evidence_refs: list[CodeChangeEvidenceRef] = []
    last_metadata = {
        "base_url_host_hash": "hash-only",
        "endpoint_type": "openai_compatible",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "model_turn_count": 2,
        "tool_call_count": 1,
    }

    def analyze(self, request: CodeChangeAnalysisRequest) -> object:
        evidence_refs = [ref.source for ref in request.evidence.evidence_refs]
        return CodeChangeAnalysis(
            what_changed="The app changed.",
            technical_summary="Updated app behavior.",
            user_or_product_impact="Developers should update documentation.",
            documentation_search_intents=["app behavior"],
            key_terms_from_code=["app"],
            evidence_refs=evidence_refs,
        )


class FakeCodeChangeLoopProvider:
    provider = "fake-loop"
    model = "fake-loop-model"

    def next_action(self, context: AgentLoopPromptContext) -> AgentLoopModelAction:
        if not any(
            observation.tool_name == AgentLoopToolName.LIST_DIRECTORY
            for observation in context.observations
        ):
            return AgentLoopModelAction(
                action=AgentLoopActionType.TOOL_CALL,
                tool_call=AgentLoopToolCall(
                    tool_name=AgentLoopToolName.LIST_DIRECTORY,
                    arguments={"path": "/repositories/repo-change-analysis/"},
                    reason="discover surrounding docs",
                ),
            )
        if not any(
            observation.tool_name == AgentLoopToolName.READ_TEXT_FILE
            and observation.payload.get("metadata", {}).get("relative_path") == "docs/guide.md"
            for observation in context.observations
        ):
            return AgentLoopModelAction(
                action=AgentLoopActionType.TOOL_CALL,
                tool_call=AgentLoopToolCall(
                    tool_name=AgentLoopToolName.READ_TEXT_FILE,
                    arguments={
                        "path": "/repositories/repo-change-analysis/docs/guide.md",
                    },
                    reason="compare code change with existing guide",
                ),
            )
        evidence_refs = [
            ref for observation in context.observations for ref in observation.evidence_refs
        ]
        return AgentLoopModelAction(
            action=AgentLoopActionType.FINAL,
            final_output=CodeChangeAnalysis(
                what_changed="The app prints the per-file summaries state.",
                technical_summary="Loop inspected app and docs evidence.",
                user_or_product_impact=(
                    "Developers can align app behavior with changed-file documentation."
                ),
                affected_components=["AppShell"],
                affected_workflows=["changed-file manifest"],
                documentation_search_intents=["changed-file manifest workflow"],
                key_terms_from_code=["per-file summaries"],
                evidence_refs=evidence_refs,
                needs_main_agent_review=True,
            ).model_dump(mode="json"),
            reasoning_summary="loop has inspected raw diff and docs context",
        )


def project_profile(project_id: str) -> ProjectProfileSnapshot:
    return ProjectProfileSnapshot(
        project_id=project_id,
        prompt_version="test-profile",
        taxonomy=ProjectTaxonomy(
            version="profile-test:v1",
            categories=["documentation-workflow"],
            components=["AppShell"],
            workflows=["changed-file manifest"],
            domain_terms=["manifest status"],
        ),
    )
