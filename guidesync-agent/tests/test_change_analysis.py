from __future__ import annotations

import subprocess
from pathlib import Path

from guidesync_agent.schemas import ChangedFileRef, ProjectCreate, ProjectRepository
from guidesync_agent.services.change_analysis import (
    summarize_changed_file,
    summarize_changed_files,
)
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
        summary.path == "src/app.py" and summary.needs_main_agent_review
        for summary in summaries
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
