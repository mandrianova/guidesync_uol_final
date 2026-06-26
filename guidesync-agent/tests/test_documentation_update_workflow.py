from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from guidesync_agent.knowledge import build_knowledge_snapshot
from guidesync_agent.pipeline import run_guidesync
from guidesync_agent.schemas import (
    GuideSyncRunRequest,
    KnowledgeIndexRequest,
    ProjectCreate,
    ProjectRepository,
    ProviderConfig,
    ProviderKind,
    ReportConfig,
    RepositoryInput,
)
from guidesync_agent.services.project_profile import build_project_profile_for_project
from guidesync_agent.storage import DatabaseProjectStore, create_knowledge_store


def run_git(repo: Path | None, args: list[str]) -> None:
    command = ["git", *args] if repo is None else ["git", "-C", str(repo), *args]
    subprocess.run(command, check=True, capture_output=True, text=True)


def create_source_repository(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "docs").mkdir(parents=True)
    (source / "src").mkdir()
    (source / "docs" / "guide.md").write_text(
        "# Workflow guide\n\nInitial workflow documentation.\n",
        encoding="utf-8",
    )
    (source / "src" / "app.py").write_text("print('initial')\n", encoding="utf-8")
    run_git(None, ["init", str(source)])
    run_git(source, ["config", "user.email", "test@example.com"])
    run_git(source, ["config", "user.name", "GuideSync Test"])
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Initial workflow docs"])
    (source / "docs" / "guide.md").write_text(
        "# Workflow guide\n\nInitial workflow documentation.\n\nDocument changed-file manifests.\n",
        encoding="utf-8",
    )
    (source / "src" / "app.py").write_text(
        "print('initial')\nprint('changed file manifest')\n",
        encoding="utf-8",
    )
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Add changed-file manifest docs"])
    run_git(source, ["branch", "-M", "main"])
    return source


def test_run_guidesync_writes_documentation_workflow_artifacts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'workflow.db'}"
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GUIDESYNC_PROJECT_PROFILE_OUTPUT_DIR", str(tmp_path / "profiles"))
    source = create_source_repository(tmp_path)
    project = DatabaseProjectStore(database_url).save(
        ProjectCreate(
            name="Workflow project",
            description="Tests documentation update workflow context.",
            knowledge_base_path="docs/",
            repositories=[
                ProjectRepository(
                    id="repo-workflow",
                    name="fixture",
                    url=str(source),
                    default_branch="main",
                    analysis_paths=["docs", "src"],
                )
            ],
        )
    )
    profile = build_project_profile_for_project(project, reason="test")
    snapshot = build_knowledge_snapshot(
        KnowledgeIndexRequest(
            project_id=project.id,
            repositories=[
                RepositoryInput(
                    name="fixture",
                    project_id=project.id,
                    repository_id="repo-workflow",
                    url=str(source),
                    ref="main",
                    paths=["docs"],
                )
            ],
        )
    )
    create_knowledge_store().save_snapshot(snapshot)
    request = GuideSyncRunRequest(
        run_id=f"{project.id}-workflow",
        goal="Document changed-file manifests for workflow guide.",
        provider=ProviderConfig(provider=ProviderKind.MOCK, model="mock:deterministic"),
        repositories=[
            RepositoryInput(
                name="fixture",
                project_id=project.id,
                repository_id="repo-workflow",
                url=str(source),
                branches=["main"],
                paths=["docs", "src"],
            )
        ],
        report=ReportConfig(output_dir=tmp_path / "run-output"),
        project_profile_snapshot_id=profile.id,
    )

    result = asyncio.run(run_guidesync(request))

    assert result.status == "completed"
    assert {
        "changed-files.json",
        "documentation-edit.json",
        "documentation.patch",
        "file-summaries.json",
        "project-profile.json",
        "retrieved-docs.json",
    } <= set(result.artifacts)
    changed_files = json.loads(
        Path(result.artifacts["changed-files.json"]).read_text(encoding="utf-8")
    )
    file_summaries = json.loads(
        Path(result.artifacts["file-summaries.json"]).read_text(encoding="utf-8")
    )
    retrieved_docs = json.loads(
        Path(result.artifacts["retrieved-docs.json"]).read_text(encoding="utf-8")
    )
    stored_profile = json.loads(
        Path(result.artifacts["project-profile.json"]).read_text(encoding="utf-8")
    )
    documentation_edit = json.loads(
        Path(result.artifacts["documentation-edit.json"]).read_text(encoding="utf-8")
    )
    markdown_report = Path(result.artifacts["report.md"]).read_text(encoding="utf-8")
    json_report = json.loads(Path(result.artifacts["run.json"]).read_text(encoding="utf-8"))

    assert {item["path"] for item in changed_files["files"]} == {
        "docs/guide.md",
        "src/app.py",
    }
    summaries = file_summaries["summaries"]
    assert {item["path"] for item in summaries} == {"docs/guide.md", "src/app.py"}
    assert all(Path(item["artifact_uri"]).exists() for item in summaries)
    assert all("diff" not in item and "content" not in item for item in summaries)
    assert all(item["analysis_artifact"]["prompt_version"] for item in summaries)
    assert all(item["analysis_artifact"]["evidence_refs"] for item in summaries)
    assert all(item["annotation_run_id"] for item in summaries)
    assert any(
        item["path"] == "src/app.py" and item["needs_main_agent_review"] is True
        for item in summaries
    )
    assert retrieved_docs["results"]
    assert stored_profile["id"] == profile.id
    assert documentation_edit["ok"] is True
    assert documentation_edit["commit_sha"]
    assert documentation_edit["changed_docs"] == ["docs/guide.md"]
    assert "documentation.patch" in markdown_report
    assert "file-summaries.json" in markdown_report
    assert "documentation.patch" in json_report["artifacts"]
    assert "file-summaries.json" in json_report["artifacts"]
    assert result.update is not None
    assert result.update.documentation_edit is not None
    assert result.update.documentation_edit.commit_sha
    assert "docs/guide.md" in result.update.proposed_update_markdown
    assert any(
        reference.source.startswith("doc-change:") for reference in result.update.evidence_used
    )
    assert any(
        reference.source.startswith("knowledge:") for reference in result.update.evidence_used
    )
