from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

from storage_test_utils import sqlite_database_url

from guidesync_agent.agent_runtime import code_change as code_change_runtime
from guidesync_agent.agent_runtime.code_change import (
    CodeChangeAnalysisEvidence,
    CodeChangeAnalysisGroupRequest,
    CodeChangeAnalysisRequest,
    PydanticAICodeChangeAnalysisProvider,
    analyze_code_change_with_subagent,
    code_change_analyzer_prompt,
    code_change_prompt,
    pydantic_code_change_group_prompt,
    pydantic_code_change_prompt,
)
from guidesync_agent.schemas import (
    AgentLoopToolName,
    ChangedFileRef,
    CodeChangeAnalysis,
    CodeChangeAnalysisModelOutput,
    CodeChangeEvidenceRef,
    CodeChangeFileAnalysisModelOutput,
    CodeChangeGroupAnalysisModelOutput,
    FileChangeSummary,
    ModelRole,
    ProjectCreate,
    ProjectProfileSnapshot,
    ProjectRepository,
    ProjectTaxonomy,
    ProviderConfig,
    ProviderKind,
    TokenUsageSource,
)
from guidesync_agent.services.change_analysis import (
    ChangeAnalysisContext,
    summarize_change_group,
    summarize_changed_file,
)
from guidesync_agent.services.change_evidence_packet import (
    changed_declaration_symbols,
    interleave_symbol_references,
)
from guidesync_agent.storage import DatabaseModelUsageStore, DatabaseProjectStore
from guidesync_agent.tools.code_change_agent import (
    code_change_tool_descriptors,
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
        "# Guide\n\nInitial workflow documentation.\n\n"
        "Document `render_changed_file_manifest` per-file summaries.\n",
        encoding="utf-8",
    )
    (source / "src" / "app.py").write_text(
        "print('initial')\n\n"
        "def render_changed_file_manifest() -> str:\n"
        "    return 'per-file summaries'\n\n"
        "print(render_changed_file_manifest())\n",
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


def change_request(*, path: str, diff: str) -> CodeChangeAnalysisRequest:
    return CodeChangeAnalysisRequest(
        project_id="project-test",
        repository_id="repo-test",
        path=path,
        status="M",
        goal="Document the change.",
        audience="developers",
        fallback_summary=FileChangeSummary(
            repository_id="repo-test",
            path=path,
            status="M",
            technical_summary="Fallback technical summary.",
            product_impact="Fallback product impact.",
        ),
        evidence=CodeChangeAnalysisEvidence(diff=diff),
    )


def test_pydantic_code_change_uses_native_output_without_retry(monkeypatch) -> None:
    captured = {}
    config = ProviderConfig(
        provider=ProviderKind.PYDANTIC_AI,
        model="openai:test-model",
    )
    monkeypatch.setattr(
        code_change_runtime,
        "provider_config_for_role",
        lambda _: config,
    )

    def fake_run(request):
        captured.update(vars(request))
        return SimpleNamespace(
            output=CodeChangeGroupAnalysisModelOutput(
                files=[
                    CodeChangeFileAnalysisModelOutput(
                        path="src/app.py",
                        technical_summary="Updated the app.",
                        user_or_product_impact="Developers see the new behavior.",
                    )
                ]
            ),
            usage={},
        )

    monkeypatch.setattr(code_change_runtime, "run_pydantic_agent_sync", fake_run)
    provider = PydanticAICodeChangeAnalysisProvider()

    provider.analyze_group(
        CodeChangeAnalysisGroupRequest(
            work_unit_id="unit-1",
            changes=[change_request(path="src/app.py", diff="+updated")],
        )
    )

    assert captured["requires_tools"] is False
    assert captured["retries"] == 0
    assert captured["register_tools"] is not None


def reference_entry(path: str, line_number: int) -> dict[str, object]:
    return {
        "relative_path": path,
        "line_number": line_number,
        "preview": f"use at line {line_number}",
        "evidence_ref": f"file:{path}:{line_number}",
    }


def test_failed_file_summary_marks_review_without_failing_run(monkeypatch, tmp_path: Path) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)

    summary = summarize_changed_file(
        ChangeAnalysisContext(
            project_id=project_id,
            repository_id=repository_id,
            goal="Document unsafe paths.",
            audience="developers",
        ),
        ChangedFileRef(path="../outside.md", status="M"),
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
        ChangeAnalysisContext(
            project_id=project_id,
            repository_id=repository_id,
            goal="Document changed-file manifests.",
            audience="developers",
            project_profile=project_profile(project_id),
            analysis_provider=provider,
        ),
        ChangedFileRef(path="src/app.py", status="M"),
    )

    assert summary.analysis_provider == "fake"
    assert summary.analysis_model == "fake-structured"
    assert summary.what_changed == "AppShell now shows the changed-file manifest status."
    assert summary.affected_components == ["AppShell"]
    assert summary.affected_workflows == ["changed-file manifest"]
    assert summary.documentation_search_intents == ["changed-file manifest workflow"]
    assert [match.value for match in summary.taxonomy_matches] == [
        "AppShell",
        "changed-file manifest",
    ]
    assert any(update.value == "billing" for update in summary.candidate_taxonomy_updates)
    assert summary.annotation_run_id
    assert summary.analysis_artifact is not None
    assert summary.analysis_artifact.prompt_version == "docs-update-code-change-analyzer-v2"
    assert summary.analysis_artifact.evidence_refs
    assert not any(
        finding.check == "code-change-analysis.taxonomy"
        for finding in summary.analysis_artifact.validation_findings
    )
    serialized = summary.model_dump(mode="json")
    assert "diff" not in serialized and "content" not in serialized


def test_change_group_uses_one_model_call_for_multiple_files(monkeypatch, tmp_path: Path) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)
    provider = FakeGroupProvider()

    summaries = summarize_change_group(
        ChangeAnalysisContext(
            project_id=project_id,
            repository_id=repository_id,
            goal="Document the cohesive change.",
            audience="developers",
            analysis_provider=provider,
        ),
        [
            ChangedFileRef(path="docs/guide.md", status="M"),
            ChangedFileRef(path="src/app.py", status="M"),
        ],
        work_unit_id="cohesive-change",
        grouping_reason="implementation and docs",
        connectivity_evidence=["shared changed symbol"],
    )

    assert provider.group_calls == 1
    assert provider.last_request is not None
    assert provider.last_request.grouping_reason == "implementation and docs"
    assert provider.last_request.connectivity_evidence == ["shared changed symbol"]
    assert provider.last_request.evidence_budget.max_tool_result_chars == 16_000
    assert provider.last_request.evidence_budget.max_changed_symbols == 12
    assert provider.last_request.changed_symbols == ["render_changed_file_manifest"]
    assert [summary.path for summary in summaries] == ["docs/guide.md", "src/app.py"]
    assert all(summary.analysis_provider == "fake-group" for summary in summaries)
    assert {snippet.symbol for snippet in provider.last_request.related_references} == {
        "render_changed_file_manifest"
    }
    assert {snippet.path for snippet in provider.last_request.related_references} == {
        "docs/guide.md",
        "src/app.py",
    }


def test_invalid_llm_change_analysis_falls_back_to_deterministic_summary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)

    summary = summarize_changed_file(
        ChangeAnalysisContext(
            project_id=project_id,
            repository_id=repository_id,
            goal="Document changed-file manifests.",
            audience="developers",
            project_profile=project_profile(project_id),
            analysis_provider=InvalidStructuredProvider(),
        ),
        ChangedFileRef(path="src/app.py", status="M"),
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
    normalized_prompt = " ".join(prompt.split())

    assert '"change":' in prompt
    assert '"initial_observations":' in prompt
    assert "available evidence tools" in prompt
    assert "plain strings" in prompt
    assert "project-profile terms" in normalized_prompt
    assert "Pydantic AI" not in prompt
    assert "tool_descriptors" not in prompt
    assert "action_contract" not in prompt
    assert "AgentLoopRequest" not in prompt

    group_prompt = pydantic_code_change_group_prompt(
        CodeChangeAnalysisGroupRequest(
            work_unit_id="unit-test",
            changes=[request],
        ),
        {request.path: initial_code_change_observations(request)},
    )
    assert '"evidence_refs": [\n          "diff:repo-test:src/app.py"' in group_prompt
    assert '"detail": "initial raw diff"' not in group_prompt


def test_changed_symbols_include_python_assignments() -> None:
    request = CodeChangeAnalysisRequest(
        project_id="project-test",
        repository_id="repo-test",
        path="fastapi/routing.py",
        status="M",
        goal="Document streaming changes.",
        audience="developers",
        fallback_summary=FileChangeSummary(
            repository_id="repo-test",
            path="fastapi/routing.py",
            status="M",
            technical_summary="Fallback technical summary.",
            product_impact="Fallback product impact.",
        ),
        evidence=CodeChangeAnalysisEvidence(
            diff=(
                "+is_json_stream: bool = response_model is DefaultPlaceholder\n"
                "+def get_stream_item_type(annotation: Any) -> Any:\n"
            )
        ),
    )

    assert changed_declaration_symbols([request]) == [
        "get_stream_item_type",
        "is_json_stream",
    ]


def test_changed_symbols_are_balanced_across_files() -> None:
    requests = [
        change_request(
            path="first.py",
            diff="+def first() -> None:\n+def second() -> None:\n+def third() -> None:\n",
        ),
        change_request(path="second.py", diff="+def other() -> None:\n"),
    ]

    assert changed_declaration_symbols(requests) == ["first", "other", "second", "third"]


def test_reference_budget_is_balanced_across_symbols() -> None:
    entries_by_symbol = {
        "first": [reference_entry("first.py", line) for line in range(1, 5)],
        "second": [reference_entry("second.py", 1)],
    }

    snippets = interleave_symbol_references(entries_by_symbol)

    assert [(snippet.symbol, snippet.line_number) for snippet in snippets] == [
        ("first", 1),
        ("second", 1),
        ("first", 2),
        ("first", 3),
        ("first", 4),
    ]


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


class FakeStructuredProvider:
    provider = "fake"
    model = "fake-structured"

    def analyze(self, request: CodeChangeAnalysisRequest) -> object:
        evidence_refs = [ref.source for ref in request.evidence.evidence_refs]
        return CodeChangeAnalysisModelOutput(
            what_changed="AppShell now shows the changed-file manifest status.",
            technical_summary="Updated AppShell to expose changed-file manifest status.",
            user_or_product_impact=(
                "Developers can see when changed-file manifest data is available."
            ),
            affected_components=["AppShell"],
            affected_workflows=["changed-file manifest"],
            documentation_search_intents=["changed-file manifest workflow"],
            taxonomy_matches=["AppShell", "changed-file manifest"],
            candidate_taxonomy_updates=["billing"],
            key_terms_from_code=["AppShell", "changed-file manifest"],
            needs_screenshot_check=True,
            evidence_refs=evidence_refs,
        )


class FakeGroupProvider:
    provider = "fake-group"
    model = "fake-group-model"

    def __init__(self) -> None:
        self.group_calls = 0
        self.last_request: CodeChangeAnalysisGroupRequest | None = None

    def analyze_group(self, request: CodeChangeAnalysisGroupRequest) -> object:
        self.group_calls += 1
        self.last_request = request
        return CodeChangeGroupAnalysisModelOutput(
            files=[
                CodeChangeFileAnalysisModelOutput(
                    path=change.path,
                    what_changed=f"Updated {change.path}.",
                    technical_summary=f"Changed {change.path} as part of one feature.",
                    user_or_product_impact="Developers get one cohesive workflow.",
                    documentation_search_intents=["cohesive workflow"],
                    key_terms_from_code=["workflow"],
                    evidence_refs=[ref.source for ref in change.evidence.evidence_refs],
                )
                for change in request.changes
            ]
        )


def test_group_model_output_accepts_common_file_path_alias() -> None:
    output = CodeChangeGroupAnalysisModelOutput.model_validate(
        {
            "files": [
                {
                    "file_path": "fastapi/routing.py",
                    "technical_summary": "Updated streaming behavior.",
                    "product_impact": "Developers can return JSONL streams.",
                }
            ]
        }
    )

    assert output.files[0].path == "fastapi/routing.py"
    assert output.files[0].user_or_product_impact == "Developers can return JSONL streams."
    assert output.files[0].to_analysis().technical_summary == "Updated streaming behavior."


class InvalidStructuredProvider:
    provider = "fake"
    model = "invalid"

    def analyze(self, request: CodeChangeAnalysisRequest) -> object:
        return {"technical_summary": "", "documentation_search_intents": []}


class UsageStructuredProvider:
    provider = ProviderKind.LOCAL_HTTP.value
    model = "openai:test-model"
    last_evidence_refs: ClassVar[list[CodeChangeEvidenceRef]] = []
    last_metadata: ClassVar[dict[str, object]] = {
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
