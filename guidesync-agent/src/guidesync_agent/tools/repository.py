from __future__ import annotations

import subprocess
from pathlib import Path

from guidesync_agent.schemas import (
    ChangedFileRef,
    ChangedFilesResult,
    ProjectConfig,
    ProjectRepository,
    RepositoryDiffWindow,
    RepositoryFileWindow,
    RepositorySearchMatch,
    RepositorySearchResult,
    ToolError,
    ToolPagination,
)
from guidesync_agent.services.repository_cache import (
    RepositoryCacheError,
    RepositoryCacheService,
    run_git,
)
from guidesync_agent.storage import create_project_store

MAX_TOOL_CHARS = 200_000
MAX_SCAN_FILE_BYTES = 1_000_000
IGNORED_SEARCH_PARTS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv"}


class RepositoryToolError(ValueError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def list_changed_files(
    project_id: str,
    repository_id: str,
    *,
    base_ref: str | None = None,
    head_ref: str = "HEAD",
) -> ChangedFilesResult:
    try:
        _, repository, root = resolve_repository(project_id, repository_id)
        base = base_ref or "HEAD~1"
        raw = run_git(root, ["diff", "--name-status", base, head_ref])
        files = []
        for line in raw.splitlines():
            status, _, path = line.partition("\t")
            if path:
                files.append(ChangedFileRef(path=path, status=status))
        return ChangedFilesResult(
            repository_id=repository.id,
            base_ref=base,
            head_ref=head_ref,
            files=files,
        )
    except Exception as exc:  # noqa: BLE001 - tools return structured errors
        return ChangedFilesResult(
            ok=False,
            repository_id=repository_id,
            base_ref=base_ref,
            head_ref=head_ref,
            error=tool_error(exc),
        )


def read_file_window(
    project_id: str,
    repository_id: str,
    path: str,
    *,
    offset: int = 0,
    limit: int = 16_000,
) -> RepositoryFileWindow:
    try:
        _, repository, root = resolve_repository(project_id, repository_id)
        file_path = safe_repository_path(root, path)
        if not file_path.is_file():
            raise RepositoryToolError("not_found", f"Repository file not found: {path}")
        data = file_path.read_bytes()
        if b"\x00" in data[:4096]:
            raise RepositoryToolError("binary_file", f"Repository file appears binary: {path}")
        text = data.decode("utf-8", errors="replace")
        content, pagination = paginate_text(text, offset=offset, limit=limit)
        return RepositoryFileWindow(
            repository_id=repository.id,
            path=Path(path).as_posix(),
            content=content,
            pagination=pagination,
        )
    except Exception as exc:  # noqa: BLE001 - tools return structured errors
        return RepositoryFileWindow(
            ok=False,
            repository_id=repository_id,
            path=path,
            pagination=empty_pagination(offset, limit),
            error=tool_error(exc),
        )


def read_diff_window(
    project_id: str,
    repository_id: str,
    *,
    path: str | None = None,
    base_ref: str | None = None,
    head_ref: str = "HEAD",
    offset: int = 0,
    limit: int = 16_000,
) -> RepositoryDiffWindow:
    try:
        _, repository, root = resolve_repository(project_id, repository_id)
        base = base_ref or "HEAD~1"
        args = ["diff", base, head_ref]
        if path:
            validate_relative_path(path)
            args.extend(["--", Path(path).as_posix()])
        raw = run_git(root, args)
        diff, pagination = paginate_text(raw, offset=offset, limit=limit)
        return RepositoryDiffWindow(
            repository_id=repository.id,
            path=Path(path).as_posix() if path else None,
            base_ref=base,
            head_ref=head_ref,
            diff=diff,
            pagination=pagination,
        )
    except Exception as exc:  # noqa: BLE001 - tools return structured errors
        return RepositoryDiffWindow(
            ok=False,
            repository_id=repository_id,
            path=path,
            base_ref=base_ref,
            head_ref=head_ref,
            pagination=empty_pagination(offset, limit),
            error=tool_error(exc),
        )


def search_repository(
    project_id: str,
    repository_id: str,
    query: str,
    *,
    path_filters: list[str] | None = None,
    limit: int = 20,
) -> RepositorySearchResult:
    try:
        _, repository, root = resolve_repository(project_id, repository_id)
        needle = query.strip().lower()
        if not needle:
            return RepositorySearchResult(query=query, matches=[], total=0)
        safe_limit = min(max(1, limit), 100)
        matches: list[RepositorySearchMatch] = []
        total = 0
        for file_path in iter_search_files(root, path_filters or ["."]):
            text = readable_file_text(file_path)
            if text is None:
                continue
            relative = file_path.relative_to(root).as_posix()
            for line_number, line in enumerate(text.splitlines(), start=1):
                if needle not in line.lower():
                    continue
                total += 1
                if len(matches) < safe_limit:
                    matches.append(
                        RepositorySearchMatch(
                            repository_id=repository.id,
                            path=relative,
                            line_number=line_number,
                            preview=line.strip()[:500],
                        )
                    )
        return RepositorySearchResult(
            query=query,
            matches=matches,
            total=total,
            truncated=total > len(matches),
        )
    except Exception as exc:  # noqa: BLE001 - tools return structured errors
        return RepositorySearchResult(
            ok=False,
            query=query,
            error=tool_error(exc),
        )


def resolve_repository(
    project_id: str,
    repository_id: str,
) -> tuple[ProjectConfig, ProjectRepository, Path]:
    project = create_project_store().get(project_id)
    if project is None:
        raise RepositoryToolError("project_not_found", f"Project not found: {project_id}")
    repository = next((item for item in project.repositories if item.id == repository_id), None)
    if repository is None:
        raise RepositoryToolError(
            "repository_not_found",
            f"Repository not found: {repository_id}",
        )
    updated = RepositoryCacheService().pull_or_checkout_ref(
        project.id,
        repository,
        repository.default_branch,
    )
    if updated.local_path is None:
        raise RepositoryToolError("cache_unavailable", "Repository cache has no local path.")
    return project, updated, Path(updated.local_path).resolve()


def safe_repository_path(root: Path, path: str) -> Path:
    validate_relative_path(path)
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise RepositoryToolError(
            "path_outside_repository",
            f"Invalid repository path: {path}",
        ) from exc
    return candidate


def validate_relative_path(path: str) -> None:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RepositoryToolError("path_outside_repository", f"Invalid repository path: {path}")


def paginate_text(text: str, *, offset: int, limit: int) -> tuple[str, ToolPagination]:
    safe_offset = max(0, offset)
    safe_limit = min(max(1, limit), MAX_TOOL_CHARS)
    total = len(text)
    end = min(total, safe_offset + safe_limit)
    next_offset = end if end < total else None
    return (
        text[safe_offset:end],
        ToolPagination(
            offset=safe_offset,
            limit=safe_limit,
            total=total,
            next_offset=next_offset,
            truncated=next_offset is not None,
        ),
    )


def empty_pagination(offset: int, limit: int) -> ToolPagination:
    return ToolPagination(offset=max(0, offset), limit=max(1, limit), total=0)


def iter_search_files(root: Path, path_filters: list[str]) -> list[Path]:
    candidates: list[Path] = []
    for path_filter in path_filters:
        base = safe_repository_path(root, path_filter)
        if base.is_file():
            candidates.append(base)
        elif base.is_dir():
            candidates.extend(path for path in base.rglob("*") if path.is_file())
    selected = []
    for candidate in sorted(set(candidates)):
        relative = candidate.relative_to(root)
        if any(part in IGNORED_SEARCH_PARTS for part in relative.parts):
            continue
        if candidate.stat().st_size > MAX_SCAN_FILE_BYTES:
            continue
        selected.append(candidate)
    return selected


def readable_file_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None
    return data.decode("utf-8", errors="replace")


def tool_error(exc: Exception) -> ToolError:
    if isinstance(exc, RepositoryToolError):
        return ToolError(code=exc.code, message=str(exc), retryable=exc.retryable)
    if isinstance(exc, RepositoryCacheError):
        return ToolError(code="repository_cache_error", message=str(exc), retryable=True)
    if isinstance(exc, subprocess.CalledProcessError):
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        return ToolError(code="git_error", message=detail, retryable=False)
    return ToolError(code=exc.__class__.__name__, message=str(exc), retryable=False)
