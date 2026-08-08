from __future__ import annotations

import subprocess
from pathlib import Path

from storage_test_utils import sqlite_database_url

from guidesync_agent.knowledge import build_knowledge_snapshot
from guidesync_agent.schemas import (
    DocumentationEditOperation,
    DocumentationEditPlan,
    DocumentationEditStatus,
    DocumentationUpdate,
    EvidenceReference,
    FileChangeSummary,
    KnowledgeIndexRequest,
    KnowledgeSearchRequest,
    ProjectCreate,
    ProjectProfileSnapshot,
    ProjectProfileStatus,
    ProjectRepository,
    ProjectTaxonomy,
    RepositoryInput,
    ReviewerCheck,
)
from guidesync_agent.services.documentation_editing import (
    DocumentationEditPlanningContext,
    apply_documentation_edit,
    plan_documentation_edit,
    validate_target_doc_path,
)
from guidesync_agent.services.documentation_editing_plans import edit_section_from_markdown
from guidesync_agent.services.repository_cache import RepositoryCacheError, RepositoryCacheService
from guidesync_agent.storage import (
    DatabaseProjectStore,
    create_knowledge_store,
    create_project_profile_store,
)


def run_git(repo: Path | None, args: list[str]) -> None:
    command = ["git", *args] if repo is None else ["git", "-C", str(repo), *args]
    subprocess.run(command, check=True, capture_output=True, text=True)


def create_source_repository(tmp_path: Path, *, with_docs: bool = True) -> Path:
    source = tmp_path / ("source-docs" if with_docs else "source-empty-docs")
    source.mkdir()
    if with_docs:
        (source / "docs").mkdir()
        (source / "docs" / "guide.md").write_text(
            "# Workflow guide\n\nInitial workflow documentation.\n\n"
            "## Highlights\n\nOld workflow notes.\n",
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
    database_url = sqlite_database_url(tmp_path / "documentation-editing.db")
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


def plan_for_test(
    project_id: str,
    goal: str,
    file_summaries: list[FileChangeSummary],
    output_dir: Path,
) -> DocumentationEditPlan:
    plan = plan_documentation_edit(
        project_id,
        DocumentationEditPlanningContext(goal=goal, file_summaries=file_summaries),
        output_dir=output_dir,
        run_id=f"{project_id}-run",
    )
    assert isinstance(plan, DocumentationEditPlan)
    return plan


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

    file_summaries = [
        FileChangeSummary(
            repository_id=repository_id,
            path="docs/guide.md",
            status="M",
            technical_summary="Changed guide.",
            product_impact="Docs changed.",
        )
    ]
    output_dir = tmp_path / "artifacts"
    edit_plan = plan_for_test(project_id, "Highlights", file_summaries, output_dir)
    result = apply_documentation_edit(
        project_id,
        create_update(),
        edit_plan,
        output_dir=output_dir,
        run_id=f"{project_id}-run",
    )

    assert result.status is DocumentationEditStatus.COMMITTED
    assert result.commit_sha
    assert result.updated_docs == ["docs/guide.md"]
    assert result.created_docs == []
    assert result.patch_artifact_uri is not None
    assert Path(result.patch_artifact_uri).exists()
    assert result.edit_plan_artifact_uri is not None
    edit_plan = Path(result.edit_plan_artifact_uri).read_text(encoding="utf-8")
    assert '"operation": "update_section"' in edit_plan
    assert result.knowledge_index_run_id
    assert result.annotation_run_ids

    edited_doc = (
        RepositoryCacheService().cache_path(project_id, repository_id) / "docs" / "guide.md"
    ).read_text(encoding="utf-8")
    assert "GuideSync Documentation Update" not in edited_doc
    assert edited_doc.count("## Highlights") == 1
    assert "Document the changed workflow and review notes." in edited_doc
    assert "Old workflow notes." not in edited_doc

    search_results = create_knowledge_store().search(
        KnowledgeSearchRequest(
            project_id=project_id,
            query="Document the changed workflow",
            limit=5,
        )
    )
    assert any(item.node.path == "docs/guide.md" for item in search_results)


def test_documentation_editor_creates_missing_doc(monkeypatch, tmp_path: Path) -> None:
    source = create_source_repository(tmp_path, with_docs=False)
    project_id, repository_id = create_project(monkeypatch, tmp_path, source)
    update = create_update().model_copy(
        update={
            "proposed_update_markdown": (
                "# Workflow documentation update\n\n"
                "## Highlights\n\nDocument the changed workflow and review notes."
            )
        }
    )

    output_dir = tmp_path / "artifacts"
    edit_plan = plan_for_test(
        project_id,
        "Workflow documentation update",
        [],
        output_dir,
    )
    result = apply_documentation_edit(
        project_id,
        update,
        edit_plan,
        output_dir=output_dir,
        run_id=f"{project_id}-run",
    )

    assert result.status is DocumentationEditStatus.COMMITTED
    assert result.commit_sha
    assert result.repository_id == repository_id
    assert result.created_docs == ["docs/workflow-documentation-update.md"]
    assert result.changed_docs == ["docs/workflow-documentation-update.md"]
    assert result.edit_plan_artifact_uri is not None
    edit_plan = Path(result.edit_plan_artifact_uri).read_text(encoding="utf-8")
    assert '"operation": "create_doc"' in edit_plan

    edited_doc = (
        RepositoryCacheService().cache_path(project_id, repository_id)
        / "docs"
        / "workflow-documentation-update.md"
    ).read_text(encoding="utf-8")
    assert edited_doc.startswith("# Workflow documentation update")
    assert edited_doc.count("# Workflow documentation update") == 1
    assert "GuideSync Documentation Update" not in edited_doc


def test_documentation_plan_prefers_retrieved_existing_doc(monkeypatch, tmp_path: Path) -> None:
    source = create_source_repository(tmp_path)
    project_id, _ = create_project(monkeypatch, tmp_path, source)

    plan = plan_documentation_edit(
        project_id,
        DocumentationEditPlanningContext(
            goal="Streaming responses",
            file_summaries=[],
            candidate_document_paths=["docs/guide.md"],
        ),
        output_dir=tmp_path / "artifacts",
        run_id=f"{project_id}-run",
    )

    assert isinstance(plan, DocumentationEditPlan)
    assert plan.target_path == "docs/guide.md"
    assert plan.items[0].operation is DocumentationEditOperation.ADD_SECTION


def test_generated_subheadings_are_normalized_below_planned_section() -> None:
    section = edit_section_from_markdown(
        "### JSONL streaming\n\nOverview.\n\n#### Automatic streaming\n\nDetails.",
        "Overview",
    )

    assert section.markdown.startswith("## Overview")
    assert "### Automatic streaming" in section.markdown
    assert "##### Automatic streaming" not in section.markdown


def test_documentation_editor_creates_new_doc_when_existing_docs_are_unrelated(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = create_source_repository(tmp_path)
    project_id, repository_id = create_project(monkeypatch, tmp_path, source)

    output_dir = tmp_path / "artifacts"
    edit_plan = plan_for_test(
        project_id,
        "Workflow documentation update",
        [],
        output_dir,
    )
    result = apply_documentation_edit(
        project_id,
        create_update(),
        edit_plan,
        output_dir=output_dir,
        run_id=f"{project_id}-run",
    )

    assert result.status is DocumentationEditStatus.COMMITTED
    assert result.repository_id == repository_id
    assert result.created_docs == ["docs/workflow-documentation-update.md"]
    assert result.updated_docs == []
    assert result.changed_docs == ["docs/workflow-documentation-update.md"]


def test_pre_generation_plan_controls_target_operation_and_section(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = create_source_repository(tmp_path)
    project_id, _ = create_project(monkeypatch, tmp_path, source)
    output_dir = tmp_path / "artifacts"
    edit_plan = plan_for_test(project_id, "Planned target", [], output_dir)

    assert edit_plan.target_path == "docs/planned-target.md"
    assert edit_plan.items[0].operation is DocumentationEditOperation.CREATE_DOC
    assert edit_plan.items[0].heading == "Overview"

    result = apply_documentation_edit(
        project_id,
        create_update(),
        edit_plan,
        output_dir=output_dir,
        run_id=f"{project_id}-run",
    )

    assert result.status is DocumentationEditStatus.COMMITTED
    assert result.edit_plan_id == edit_plan.id
    assert result.executed_plan_item_ids == [edit_plan.items[0].id]
    assert result.created_docs == ["docs/planned-target.md"]
    edited_doc = (
        RepositoryCacheService().cache_path(project_id, "repo-docs")
        / "docs"
        / "planned-target.md"
    ).read_text(encoding="utf-8")
    assert "## Overview" in edited_doc
    assert not (
        RepositoryCacheService().cache_path(project_id, "repo-docs")
        / "docs"
        / "workflow-documentation-update.md"
    ).exists()


def test_documentation_editor_rejects_update_without_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = create_source_repository(tmp_path)
    project_id, repository_id = create_project(monkeypatch, tmp_path, source)
    update = create_update().model_copy(update={"evidence_used": []})

    file_summaries = [
        FileChangeSummary(
            repository_id=repository_id,
            path="docs/guide.md",
            status="M",
            technical_summary="Changed guide.",
            product_impact="Docs changed.",
        )
    ]
    output_dir = tmp_path / "artifacts"
    edit_plan = plan_for_test(project_id, "Highlights", file_summaries, output_dir)
    result = apply_documentation_edit(
        project_id,
        update,
        edit_plan,
        output_dir=output_dir,
        run_id=f"{project_id}-run",
    )

    assert result.status is DocumentationEditStatus.FAILED
    assert result.warnings == ["documentation edit requires at least one evidence reference"]


def test_documentation_editor_rejects_target_outside_docs() -> None:
    try:
        validate_target_doc_path("docs", "../outside.md")
    except RepositoryCacheError as exc:
        assert "documentation target must stay under `docs`" in str(exc)
    else:  # pragma: no cover - explicit failure reads clearer than pytest.raises here.
        raise AssertionError("unsafe target path was accepted")


def test_documentation_editor_reannotation_marks_uncontrolled_terms_for_review(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = create_source_repository(tmp_path)
    project_id, repository_id = create_project(monkeypatch, tmp_path, source)
    create_project_profile_store().save(
        ProjectProfileSnapshot(
            id="profile-doc-editing",
            project_id=project_id,
            status=ProjectProfileStatus.COMPLETED,
            prompt_version="project-profile-analyzer-v1",
            taxonomy=ProjectTaxonomy(
                version="profile-doc-editing:v1",
                categories=["documentation-workflow"],
                workflows=["review documentation"],
                documentation_areas=["workflow guide"],
                domain_terms=["workflow documentation"],
            ),
        )
    )
    update = create_update().model_copy(
        update={
            "proposed_update_markdown": (
                "## Billing workflow\n\nDocument billing workflow notes for reviewers."
            )
        }
    )

    file_summaries = [
        FileChangeSummary(
            repository_id=repository_id,
            path="docs/guide.md",
            status="M",
            technical_summary="Changed guide.",
            product_impact="Docs changed.",
        )
    ]
    output_dir = tmp_path / "artifacts"
    edit_plan = plan_for_test(project_id, "Billing workflow", file_summaries, output_dir)
    result = apply_documentation_edit(
        project_id,
        update,
        edit_plan,
        output_dir=output_dir,
        run_id=f"{project_id}-run",
    )

    assert result.status is DocumentationEditStatus.COMMITTED
    assert result.annotation_run_ids

    search_results = create_knowledge_store().search(
        KnowledgeSearchRequest(
            project_id=project_id,
            query="billing",
            categories=["billing"],
            taxonomy_version="profile-doc-editing:v1",
            limit=5,
        )
    )
    guide_result = next(item for item in search_results if item.node.path == "docs/guide.md")
    assert guide_result.diagnostics.warnings == [
        "candidate taxonomy terms require review and were not ranked as controlled categories"
    ]
