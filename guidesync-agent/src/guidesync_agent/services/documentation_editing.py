from __future__ import annotations

import re
import subprocess
from pathlib import Path

from guidesync_agent.knowledge import build_knowledge_snapshot, is_documentation_path
from guidesync_agent.schemas import (
    DocumentationEditResult,
    DocumentationUpdate,
    FileChangeSummary,
    KnowledgeIndexRequest,
    ProjectConfig,
    ProjectRepository,
    RepositoryInput,
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


def apply_documentation_edit(
    project_id: str,
    update: DocumentationUpdate,
    file_summaries: list[FileChangeSummary],
    *,
    output_dir: Path,
    run_id: str,
) -> DocumentationEditResult:
    output_dir.mkdir(parents=True, exist_ok=True)
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
    target_path = select_target_doc(root, docs_path, update, file_summaries)
    target_file = safe_repository_path(root, target_path)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    existed = target_file.exists()
    target_file.write_text(
        render_updated_document(target_file, update, existed),
        encoding="utf-8",
    )

    if not existed:
        run_git(root, ["add", "--intent-to-add", "--", target_path])
    diff = run_git(root, ["diff", "--", target_path])
    patch_path = output_dir / "documentation.patch"
    patch_path.write_text(diff, encoding="utf-8")
    result = DocumentationEditResult(
        ok=False,
        repository_id=repository.id,
        docs_path=docs_path,
        target_path=target_path,
        changed_docs=[target_path],
        created_docs=[] if existed else [target_path],
        updated_docs=[target_path] if existed else [],
        base_commit=base_commit,
        patch_artifact_uri=str(patch_path),
    )
    if not diff.strip():
        return result.model_copy(
            update={
                "ok": True,
                "warnings": ["documentation edit produced no file diff"],
            }
        )

    commit_message = commit_message_for(update)
    try:
        ensure_git_identity(root)
        run_git(root, ["add", "--", target_path])
        run_git(root, ["commit", "-m", commit_message])
    except subprocess.CalledProcessError as exc:
        return result.model_copy(
            update={
                "warnings": [f"documentation commit failed: {git_error_detail(exc)}"],
                "commit_message": commit_message,
            }
        )

    commit_sha = RepositoryCacheService().current_commit(root)
    index_run_id = reindex_changed_docs(
        project,
        repository,
        root,
        [target_path],
    )
    return result.model_copy(
        update={
            "ok": True,
            "commit_sha": commit_sha,
            "commit_message": commit_message,
            "knowledge_index_run_id": index_run_id,
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
    update: DocumentationUpdate,
    file_summaries: list[FileChangeSummary],
) -> str:
    for summary in file_summaries:
        path = Path(summary.path).as_posix()
        if path_within_prefix(path, docs_path) and is_documentation_path(path):
            if safe_repository_path(root, path).exists():
                return path
    return str(Path(docs_path) / f"{safe_slug(update.title, MAX_TITLE_SLUG_CHARS)}.md")


def render_updated_document(
    target_file: Path,
    update: DocumentationUpdate,
    existed: bool,
) -> str:
    section = "\n".join(
        [
            "## GuideSync Documentation Update",
            "",
            update.summary.strip(),
            "",
            "### Proposed Release Notes",
            "",
            update.proposed_update_markdown.strip(),
            "",
        ]
    )
    if not existed:
        return f"# {update.title.strip() or 'GuideSync Documentation Update'}\n\n{section}"
    existing = target_file.read_text(encoding="utf-8", errors="replace").rstrip()
    return f"{existing}\n\n{section}"


def reindex_changed_docs(
    project: ProjectConfig,
    repository: ProjectRepository,
    root: Path,
    changed_docs: list[str],
) -> str | None:
    profile = latest_project_profile(project.id)
    taxonomy = profile.taxonomy if profile and profile.status == "completed" else None
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
            max_files=max(len(changed_docs), 1),
        )
    )
    create_knowledge_store().save_changed_docs_snapshot(snapshot, set(changed_docs))
    return snapshot.run.id


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
) -> DocumentationEditResult:
    return DocumentationEditResult(
        ok=False,
        repository_id=repository_id,
        docs_path=docs_path,
        target_path=target_path,
        warnings=[warning],
    )


def git_error_detail(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        return exc.stderr.strip() or exc.stdout.strip() or str(exc)
    return str(exc)
