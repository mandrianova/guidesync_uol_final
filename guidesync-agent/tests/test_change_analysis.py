from __future__ import annotations

import subprocess
from pathlib import Path

from guidesync_agent.schemas import (
    ChangedFileRef,
    CodeChangeAnalysis,
    CodeChangeCandidateTaxonomyUpdate,
    CodeChangeTaxonomyMatch,
    KnowledgeConceptKind,
    ProjectCreate,
    ProjectProfileSnapshot,
    ProjectRepository,
    ProjectTaxonomy,
)
from guidesync_agent.services.change_analysis import (
    summarize_changed_file,
    summarize_changed_files,
)
from guidesync_agent.services.code_change_subagent import CodeChangeAnalysisRequest
from guidesync_agent.storage import DatabaseProjectStore


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
    database_url = f"sqlite+pysqlite:///{tmp_path / 'change-analysis.db'}"
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
