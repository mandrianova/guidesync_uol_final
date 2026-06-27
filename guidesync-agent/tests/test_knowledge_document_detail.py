from __future__ import annotations

import subprocess
from pathlib import Path

from guidesync_agent.controllers.knowledge import (
    create_project_index_run,
    document_detail,
    document_refs,
)
from guidesync_agent.schemas import ProjectCreate, ProjectKnowledgeIndexRequest, ProjectRepository
from guidesync_agent.storage import DatabaseProjectStore


def run_git(repo: Path | None, args: list[str]) -> None:
    command = ["git", *args] if repo is None else ["git", "-C", str(repo), *args]
    subprocess.run(command, check=True, capture_output=True, text=True)


def test_knowledge_document_detail_reads_markdown_from_indexed_commit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'knowledge-detail.db'}"
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "cache"))
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "guide.md").write_text(
        "# Guide\n\nOpen the project profile before running analysis.\n",
        encoding="utf-8",
    )
    run_git(None, ["init", str(repo)])
    run_git(repo, ["config", "user.email", "test@example.com"])
    run_git(repo, ["config", "user.name", "GuideSync Test"])
    run_git(repo, ["add", "."])
    run_git(repo, ["commit", "-m", "Add guide"])
    run_git(repo, ["branch", "-M", "main"])
    project = DatabaseProjectStore(database_url).save(
        ProjectCreate(
            name="Knowledge detail project",
            knowledge_base_path="docs",
            repositories=[
                ProjectRepository(
                    id="repo-detail",
                    name="detail-repo",
                    url=str(repo),
                    default_branch="main",
                )
            ],
        )
    )
    create_project_index_run(project.id, ProjectKnowledgeIndexRequest())
    documents = document_refs(project.id).documents

    detail = document_detail(project.id, documents[0].id)

    assert detail.document.path == "docs/guide.md"
    assert "# Guide" in detail.markdown
    assert detail.source_commit
    assert not detail.truncated
