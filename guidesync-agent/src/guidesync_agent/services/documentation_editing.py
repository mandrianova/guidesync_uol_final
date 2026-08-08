from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from guidesync_agent.knowledge import build_knowledge_snapshot, is_documentation_path
from guidesync_agent.schemas import (
    DocumentationEditOperation,
    DocumentationEditPlan,
    DocumentationEditPlanItem,
    DocumentationEditResult,
    DocumentationEditSection,
    DocumentationEditStatus,
    DocumentationUpdate,
    FileChangeSummary,
    KnowledgeIndexRequest,
    ProjectConfig,
    ProjectProfileStatus,
    ProjectRepository,
    RepositoryInput,
)
from guidesync_agent.services.documentation_editing_plans import (
    DocumentationEditPlanInput,
    build_edit_plan,
    edit_section_from_markdown,
    planned_section_heading,
    write_json_artifact,
)
from guidesync_agent.services.documentation_editing_sections import (
    markdown_section_exists,
    replace_markdown_section,
)
from guidesync_agent.services.project_profile import latest_project_profile
from guidesync_agent.services.repository_cache import (
    RepositoryCacheError,
    RepositoryCacheService,
    RepositoryCacheStatus,
    run_git,
)
from guidesync_agent.storage import create_knowledge_store, create_project_store

MAX_TITLE_SLUG_CHARS = 54


class ReindexChangedDocsResult(BaseModel):
    index_run_id: str | None = None
    annotation_run_ids: list[str] | None = None
    warnings: list[str] | None = None


@dataclass(frozen=True)
class PreparedDocumentationEdit:
    project: ProjectConfig
    repository: ProjectRepository
    docs_path: str
    root: Path
    base_commit: str | None


@dataclass(frozen=True)
class DraftDocumentationEdit:
    result: DocumentationEditResult
    target_path: str
    diff: str


@dataclass(frozen=True)
class DocumentationEditPlanningContext:
    goal: str
    file_summaries: list[FileChangeSummary]
    candidate_document_paths: Sequence[str] = ()


def apply_documentation_edit(
    project_id: str,
    update: DocumentationUpdate,
    edit_plan: DocumentationEditPlan,
    *,
    output_dir: Path,
    run_id: str,
) -> DocumentationEditResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared = prepare_documentation_edit(project_id, run_id)
    if isinstance(prepared, DocumentationEditResult):
        return prepared.model_copy(update={"edit_plan_id": edit_plan.id})
    draft = draft_documentation_edit(
        prepared,
        update,
        edit_plan,
        output_dir=output_dir,
    )
    if isinstance(draft, DocumentationEditResult):
        return draft
    return finalize_documentation_edit(prepared, draft, update)


def plan_documentation_edit(
    project_id: str,
    context: DocumentationEditPlanningContext,
    *,
    output_dir: Path,
    run_id: str,
) -> DocumentationEditPlan | DocumentationEditResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared = prepare_documentation_edit(project_id, run_id)
    if isinstance(prepared, DocumentationEditResult):
        return prepared
    target_path = select_target_doc(
        prepared.root,
        prepared.docs_path,
        context.goal,
        context.file_summaries,
        context.candidate_document_paths,
    )
    try:
        target_path = validate_target_doc_path(prepared.docs_path, target_path)
        target_file = safe_repository_path(prepared.root, target_path)
    except RepositoryCacheError as exc:
        return failed_edit_result(
            repository_id=prepared.repository.id,
            docs_path=prepared.docs_path,
            target_path=target_path,
            warning=str(exc),
        )
    edit_plan = build_edit_plan(
        DocumentationEditPlanInput(
            project_id=project_id,
            run_id=run_id,
            target_file=target_file,
            target_path=target_path,
            docs_path=prepared.docs_path,
            goal=context.goal,
            file_summaries=context.file_summaries,
            existed=target_file.exists(),
            section_heading=(
                planned_section_heading(context.goal) if target_file.exists() else "Overview"
            ),
        )
    )
    write_json_artifact(
        output_dir / "documentation-edit-plan.json",
        edit_plan.model_dump(mode="json"),
    )
    return edit_plan


def prepare_documentation_edit(
    project_id: str,
    run_id: str,
) -> PreparedDocumentationEdit | DocumentationEditResult:
    project = create_project_store().get(project_id)
    if project is None:
        return failed_edit_result(
            repository_id="",
            docs_path="",
            target_path="",
            warning=f"project not found: {project_id}",
        )

    repository = documentation_repository(project)
    if repository is None:
        return failed_edit_result(
            repository_id="",
            docs_path=project.knowledge_base_path,
            target_path="",
            warning="project has no configured documentation repository",
        )

    docs_path = normalize_docs_path(project.knowledge_base_path)
    try:
        root, repository = prepare_edit_worktree(project.id, repository, run_id)
    except (RepositoryCacheError, subprocess.CalledProcessError, OSError) as exc:
        return failed_edit_result(
            repository_id=repository.id,
            docs_path=docs_path,
            target_path="",
            warning=f"documentation repository checkout failed: {git_error_detail(exc)}",
        )
    base_commit = RepositoryCacheService().current_commit(root)
    return PreparedDocumentationEdit(project, repository, docs_path, root, base_commit)


def draft_documentation_edit(
    prepared: PreparedDocumentationEdit,
    update: DocumentationUpdate,
    edit_plan: DocumentationEditPlan,
    *,
    output_dir: Path,
) -> DraftDocumentationEdit | DocumentationEditResult:
    root = prepared.root
    docs_path = prepared.docs_path
    repository = prepared.repository
    target_path = edit_plan.target_path
    try:
        validate_edit_input(update)
        plan_item = validate_edit_plan(prepared, edit_plan)
        target_path = validate_target_doc_path(docs_path, target_path)
        target_file = safe_repository_path(root, target_path)
        validate_plan_preconditions(target_file, plan_item)
    except RepositoryCacheError as exc:
        return failed_edit_result(
            repository_id=repository.id,
            docs_path=docs_path,
            target_path=target_path,
            warning=str(exc),
            edit_plan=edit_plan,
        )
    existed = target_file.exists()
    target_file.parent.mkdir(parents=True, exist_ok=True)
    edit_section = edit_section_from_markdown(
        update.proposed_update_markdown,
        plan_item.heading,
    )
    edit_plan_path = output_dir / "documentation-edit-plan.json"
    write_json_artifact(edit_plan_path, edit_plan.model_dump(mode="json"))
    target_file.write_text(
        render_updated_document(target_file, update, plan_item.operation, edit_section),
        encoding="utf-8",
    )

    if not existed:
        run_git(root, ["add", "--intent-to-add", "--", target_path])
    diff = run_git(root, ["diff", "--", target_path])
    patch_path = output_dir / "documentation.patch"
    patch_path.write_text(diff, encoding="utf-8")
    result = DocumentationEditResult(
        status=DocumentationEditStatus.PATCH_ONLY,
        repository_id=repository.id,
        docs_path=docs_path,
        target_path=target_path,
        changed_docs=[target_path],
        created_docs=[] if existed else [target_path],
        updated_docs=[target_path] if existed else [],
        base_commit=prepared.base_commit,
        patch_artifact_uri=str(patch_path),
        edit_plan_artifact_uri=str(edit_plan_path),
        edit_plan_id=edit_plan.id,
        executed_plan_item_ids=[plan_item.id],
    )
    return DraftDocumentationEdit(result, target_path, diff)


def finalize_documentation_edit(
    prepared: PreparedDocumentationEdit,
    draft: DraftDocumentationEdit,
    update: DocumentationUpdate,
) -> DocumentationEditResult:
    result = draft.result
    target_path = draft.target_path
    diff = draft.diff
    if not diff.strip():
        return result.model_copy(
            update={
                "status": DocumentationEditStatus.NO_CHANGES,
                "warnings": ["documentation edit produced no file diff"],
            }
        )

    commit_message = commit_message_for(update)
    try:
        ensure_git_identity(prepared.root)
        run_git(prepared.root, ["add", "--", target_path])
        run_git(prepared.root, ["commit", "-m", commit_message])
    except subprocess.CalledProcessError as exc:
        return result.model_copy(
            update={
                "warnings": [f"documentation commit failed: {git_error_detail(exc)}"],
                "commit_message": commit_message,
            }
        )

    commit_sha = RepositoryCacheService().current_commit(prepared.root)
    reindex_result = reindex_changed_docs(
        prepared.project,
        prepared.repository,
        prepared.root,
        [target_path],
    )
    return result.model_copy(
        update={
            "status": DocumentationEditStatus.COMMITTED,
            "commit_sha": commit_sha,
            "commit_message": commit_message,
            "knowledge_index_run_id": reindex_result.index_run_id,
            "annotation_run_ids": reindex_result.annotation_run_ids or [],
            "annotation_warnings": reindex_result.warnings or [],
        }
    )


def documentation_repository(project: ProjectConfig) -> ProjectRepository | None:
    if not project.repositories:
        return None
    if project.knowledge_base_repository_id:
        match = next(
            (
                repository
                for repository in project.repositories
                if repository.id == project.knowledge_base_repository_id
            ),
            None,
        )
        if match is not None:
            return match
    return project.repositories[0]


def prepare_edit_worktree(
    project_id: str,
    repository: ProjectRepository,
    run_id: str,
) -> tuple[Path, ProjectRepository]:
    service = RepositoryCacheService()
    updated = service.pull_or_checkout_ref(project_id, repository, repository.default_branch)
    if updated.cache_status == RepositoryCacheStatus.FAILED:
        raise RepositoryCacheError("; ".join(updated.cache_warnings) or "repository sync failed")
    if updated.local_path is None:
        raise RepositoryCacheError("repository sync did not produce a local path")
    root = Path(updated.local_path).resolve()
    branch = f"guidesync-docs-{safe_slug(run_id, 32)}"
    run_git(root, ["checkout", "-B", branch])
    return root, updated


def select_target_doc(
    root: Path,
    docs_path: str,
    goal: str,
    file_summaries: list[FileChangeSummary],
    candidate_document_paths: Sequence[str] = (),
) -> str:
    for summary in file_summaries:
        path = Path(summary.path).as_posix()
        if path_within_prefix(path, docs_path) and is_documentation_path(path):
            if safe_repository_path(root, path).exists():
                return path
    for candidate_path in candidate_document_paths:
        path = Path(candidate_path).as_posix()
        if path_within_prefix(path, docs_path) and is_documentation_path(path):
            if safe_repository_path(root, path).exists():
                return path
    return str(Path(docs_path) / f"{safe_slug(goal, MAX_TITLE_SLUG_CHARS)}.md")


def render_updated_document(
    target_file: Path,
    update: DocumentationUpdate,
    operation: DocumentationEditOperation,
    edit_section: DocumentationEditSection,
) -> str:
    if operation is DocumentationEditOperation.CREATE_DOC:
        title = update.title.strip() or edit_section.heading
        return f"# {title}\n\n{edit_section.markdown.rstrip()}\n"
    existing = target_file.read_text(encoding="utf-8", errors="replace")
    if operation is DocumentationEditOperation.UPDATE_SECTION:
        return replace_markdown_section(existing, edit_section.heading, edit_section.markdown)
    return f"{existing.rstrip()}\n\n{edit_section.markdown.rstrip()}\n"


def validate_edit_plan(
    prepared: PreparedDocumentationEdit,
    edit_plan: DocumentationEditPlan,
) -> DocumentationEditPlanItem:
    if normalize_docs_path(edit_plan.docs_path) != prepared.docs_path:
        raise RepositoryCacheError("documentation edit plan targets a different docs root")
    if len(edit_plan.items) != 1:
        raise RepositoryCacheError("documentation edit plan must contain exactly one edit item")
    item = edit_plan.items[0]
    if item.path != edit_plan.target_path:
        raise RepositoryCacheError("documentation edit plan item does not match its target path")
    if not item.heading.strip():
        raise RepositoryCacheError("documentation edit plan requires a section heading")
    return item


def validate_plan_preconditions(
    target_file: Path,
    plan_item: DocumentationEditPlanItem,
) -> None:
    exists = target_file.exists()
    if plan_item.operation is DocumentationEditOperation.CREATE_DOC:
        if exists:
            raise RepositoryCacheError("create_doc plan target already exists")
        return
    if not exists:
        raise RepositoryCacheError(f"{plan_item.operation.value} plan target does not exist")
    section_exists = markdown_section_exists(
        target_file.read_text(encoding="utf-8", errors="replace"),
        plan_item.heading,
    )
    if plan_item.operation is DocumentationEditOperation.UPDATE_SECTION and not section_exists:
        raise RepositoryCacheError("update_section plan heading does not exist")
    if plan_item.operation is DocumentationEditOperation.ADD_SECTION and section_exists:
        raise RepositoryCacheError("add_section plan heading already exists")


def validate_target_doc_path(docs_path: str, target_path: str) -> str:
    normalized = Path(target_path).as_posix().strip("/")
    if not path_within_prefix(normalized, docs_path):
        docs_root = normalize_docs_path(docs_path)
        raise RepositoryCacheError(
            f"documentation target must stay under `{docs_root}`: {target_path}"
        )
    if not is_documentation_path(normalized):
        raise RepositoryCacheError(f"documentation target must be a markdown file: {target_path}")
    return normalized


def validate_edit_input(update: DocumentationUpdate) -> None:
    if not update.proposed_update_markdown.strip():
        raise RepositoryCacheError("documentation edit requires non-empty markdown")
    if not update.evidence_used:
        raise RepositoryCacheError("documentation edit requires at least one evidence reference")


def reindex_changed_docs(
    project: ProjectConfig,
    repository: ProjectRepository,
    root: Path,
    changed_docs: list[str],
) -> ReindexChangedDocsResult:
    profile = latest_project_profile(project.id)
    taxonomy = (
        profile.taxonomy if profile and profile.status == ProjectProfileStatus.COMPLETED else None
    )
    taxonomy_version = (
        taxonomy.version or f"{profile.id}:v{profile.version}"
        if profile is not None and taxonomy is not None
        else None
    )
    snapshot = build_knowledge_snapshot(
        KnowledgeIndexRequest(
            project_id=project.id,
            taxonomy=taxonomy,
            taxonomy_version=taxonomy_version,
            repositories=[
                RepositoryInput(
                    name=repository.name,
                    project_id=project.id,
                    repository_id=repository.id,
                    url=repository.url,
                    local_path=root,
                    ref="HEAD",
                    paths=changed_docs,
                    max_commits=1,
                )
            ],
        )
    )
    create_knowledge_store().save_changed_docs_snapshot(snapshot, set(changed_docs))
    return ReindexChangedDocsResult(
        index_run_id=snapshot.run.id,
        annotation_run_ids=[run.id for run in snapshot.annotation_runs],
        warnings=snapshot.run.summary.warnings,
    )


def normalize_docs_path(value: str) -> str:
    normalized = Path(value or "docs").as_posix().strip("/")
    if not normalized or normalized == ".":
        return "docs"
    if normalized.startswith("..") or "/../" in f"/{normalized}/":
        return "docs"
    return normalized


def path_within_prefix(path: str, prefix: str) -> bool:
    normalized_path = Path(path).as_posix().strip("/")
    normalized_prefix = normalize_docs_path(prefix).rstrip("/")
    return normalized_path == normalized_prefix or normalized_path.startswith(
        f"{normalized_prefix}/"
    )


def safe_repository_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        message = f"documentation path escapes repository: {relative_path}"
        raise RepositoryCacheError(message) from exc
    return candidate


def ensure_git_identity(root: Path) -> None:
    if not git_config(root, "user.email"):
        run_git(root, ["config", "user.email", "guidesync@example.invalid"])
    if not git_config(root, "user.name"):
        run_git(root, ["config", "user.name", "GuideSync Documentation Editor"])


def git_config(root: Path, key: str) -> str:
    try:
        return run_git(root, ["config", "--get", key]).strip()
    except subprocess.CalledProcessError:
        return ""


def commit_message_for(update: DocumentationUpdate) -> str:
    title = re.sub(r"\s+", " ", update.title).strip() or "documentation update"
    return f"docs: update {title[:72]}"


def safe_slug(value: str, limit: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "documentation-update")[:limit].strip("-") or "documentation-update"


def failed_edit_result(
    *,
    repository_id: str,
    docs_path: str,
    target_path: str,
    warning: str,
    edit_plan: DocumentationEditPlan | None = None,
) -> DocumentationEditResult:
    return DocumentationEditResult(
        status=DocumentationEditStatus.FAILED,
        repository_id=repository_id,
        docs_path=docs_path,
        target_path=target_path,
        edit_plan_id=edit_plan.id if edit_plan else None,
        warnings=[warning],
    )


def git_error_detail(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        return exc.stderr.strip() or exc.stdout.strip() or str(exc)
    return str(exc)
