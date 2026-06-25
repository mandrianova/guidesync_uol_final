from __future__ import annotations

import subprocess
from pathlib import Path

from guidesync_agent.knowledge import build_knowledge_snapshot
from guidesync_agent.schemas import (
    DocumentationUpdate,
    EvidenceReference,
    FileChangeSummary,
    KnowledgeIndexRequest,
    KnowledgeSearchRequest,
    ProjectCreate,
    ProjectRepository,
    RepositoryInput,
    ReviewerCheck,
)
from guidesync_agent.services.documentation_editing import apply_documentation_edit
from guidesync_agent.storage import DatabaseProjectStore, create_knowledge_store


def run_git(repo: Path | None, args: list[str]) -> None:
    command = ["git", *args] if repo is None else ["git", "-C", str(repo), *args]
    subprocess.run(command, check=True, capture_output=True, text=True)


def create_source_repository(tmp_path: Path, *, with_docs: bool = True) -> Path:
    source = tmp_path / ("source-docs" if with_docs else "source-empty-docs")
    source.mkdir()
    if with_docs:
        (source / "docs").mkdir()
        (source / "docs" / "guide.md").write_text(
            "# Workflow guide\n\nInitial workflow documentation.\n",
            encoding="utf-8",
        )
    else:
        (source / "src").mkdir()
        (source / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    run_git(None, ["init", str(source)])
    run_git(source, ["config", "user.email", "test@example.com"])
    run_git(source, ["config", "user.name", "GuideSync Test"])
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Initial project"])
    run_git(source, ["branch", "-M", "main"])
    return source


def create_update() -> DocumentationUpdate:
    return DocumentationUpdate(
        title="Workflow documentation update",
        summary="Document the workflow changes for reviewers.",
        user_facing_change="Reviewers can see the workflow documentation changes.",
        proposed_update_markdown=(
            "## Highlights\n\nDocument the changed workflow and review notes."
        ),
        evidence_used=[
            EvidenceReference(
                source="git:fixture:abc123",
                detail="Changed workflow",
                relevance="Grounds the documentation edit.",
            )
        ],
        reviewer_checks=[
            ReviewerCheck(name="Evidence", status="pass", notes="Evidence is cited."),
            ReviewerCheck(name="Review", status="required", notes="Check wording."),
        ],
    )


def create_project(monkeypatch, tmp_path: Path, source: Path) -> tuple[str, str]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'documentation-editing.db'}"
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "cache"))
    project = DatabaseProjectStore(database_url).save(
        ProjectCreate(
            name="Documentation editing project",
            knowledge_base_repository_id="repo-docs",
            knowledge_base_path="docs/",
            repositories=[
                ProjectRepository(
                    id="repo-docs",
                    name="fixture",
                    url=str(source),
                    default_branch="main",
                    analysis_paths=["docs"],
                )
            ],
        )
    )
    return project.id, "repo-docs"


def test_documentation_editor_updates_existing_doc_and_reindexes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = create_source_repository(tmp_path)
    project_id, repository_id = create_project(monkeypatch, tmp_path, source)
    snapshot = build_knowledge_snapshot(
        KnowledgeIndexRequest(
            project_id=project_id,
            repositories=[
                RepositoryInput(
                    name="fixture",
                    project_id=project_id,
                    repository_id=repository_id,
                    url=str(source),
                    ref="main",
                    paths=["docs"],
                )
            ],
        )
    )
    create_knowledge_store().save_snapshot(snapshot)

    result = apply_documentation_edit(
        project_id,
        create_update(),
        [
            FileChangeSummary(
                repository_id=repository_id,
                path="docs/guide.md",
                status="M",
                technical_summary="Changed guide.",
                product_impact="Docs changed.",
            )
        ],
        output_dir=tmp_path / "artifacts",
        run_id=f"{project_id}-run",
    )

    assert result.ok is True
    assert result.commit_sha
    assert result.updated_docs == ["docs/guide.md"]
    assert result.created_docs == []
    assert result.patch_artifact_uri is not None
    assert Path(result.patch_artifact_uri).exists()
    assert result.knowledge_index_run_id

    search_results = create_knowledge_store().search(
        KnowledgeSearchRequest(
            project_id=project_id,
            query="GuideSync Documentation Update",
            limit=5,
        )
    )
    assert any(item.node.path == "docs/guide.md" for item in search_results)


def test_documentation_editor_creates_missing_doc(monkeypatch, tmp_path: Path) -> None:
    source = create_source_repository(tmp_path, with_docs=False)
    project_id, repository_id = create_project(monkeypatch, tmp_path, source)

    result = apply_documentation_edit(
        project_id,
        create_update(),
        [],
        output_dir=tmp_path / "artifacts",
        run_id=f"{project_id}-run",
    )

    assert result.ok is True
    assert result.commit_sha
    assert result.repository_id == repository_id
    assert result.created_docs == ["docs/workflow-documentation-update.md"]
    assert result.changed_docs == ["docs/workflow-documentation-update.md"]
