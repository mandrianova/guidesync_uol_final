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
from guidesync_agent.services.project_profile.sources import (
    PROFILE_SKIP_PARTS,
    is_likely_secret_path,
)
from guidesync_agent.services.repositories.cache import (
    RepositoryCacheError,
    RepositoryCacheService,
    git_ref_candidates,
    run_git,
)
from guidesync_agent.storage import create_project_store

MAX_TOOL_CHARS = 200_000
MAX_SCAN_FILE_BYTES = 1_000_000


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
        project, repository, root = resolve_repository(project_id, repository_id)
        base = base_ref or "HEAD~1"
        args = ["diff", "--name-status", base, head_ref]
        analysis_paths = repository.analysis_paths or project.analysis_paths
        if analysis_paths:
            args.extend(["--", *analysis_paths])
        raw = run_git(root, args)
        files = []
        for line in raw.splitlines():
            fields = line.split("\t")
            if len(fields) < 2:
                continue
            status, path = fields[0], fields[-1]
            try:
                validate_visible_repository_path(path)
            except RepositoryToolError as exc:
                if exc.code == "path_filtered":
                    continue
                raise
            files.append(ChangedFileRef(path=path, status=status))
        return ChangedFilesResult(
            repository_id=repository.id,
            base_ref=base,
            head_ref=head_ref,
            files=files,
        )
    except Exception as exc:  # noqa: BLE001 - tools return structured errors
        return ChangedFilesResult(
            repository_id=repository_id,
            base_ref=base_ref,
            head_ref=head_ref,
            error=tool_error(exc),
        )


def read_file_window(  # noqa: PLR0913 - public bounded file tool contract
    project_id: str,
    repository_id: str,
    path: str,
    *,
    ref: str | None = None,
    offset: int = 0,
    limit: int = 16_000,
) -> RepositoryFileWindow:
    try:
        _, repository, root = resolve_repository(project_id, repository_id)
        data = read_repository_file_bytes(root, path, ref=ref)
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
            repository_id=repository_id,
            path=path,
            pagination=empty_pagination(offset, limit),
            error=tool_error(exc),
        )


def read_repository_file_bytes(root: Path, path: str, *, ref: str | None) -> bytes:
    validate_visible_repository_path(path)
    if ref is None:
        file_path = safe_repository_path(root, path)
        if not file_path.is_file():
            raise RepositoryToolError("not_found", f"Repository file not found: {path}")
        if file_path.stat().st_size > MAX_SCAN_FILE_BYTES:
            raise RepositoryToolError("file_too_large", f"Repository file is too large: {path}")
        return file_path.read_bytes()

    normalized_path = Path(path).as_posix()
    commit = resolve_commit_ref(root, ref)
    raw_entry = run_git(
        root,
        [
            "ls-tree",
            "--format=%(objecttype) %(objectname)",
            commit,
            "--",
            f":(literal){normalized_path}",
        ],
    ).strip()
    if not raw_entry:
        raise RepositoryToolError(
            "not_found",
            f"Repository file not found at {ref}: {path}",
        )
    object_type, _, object_id = raw_entry.partition(" ")
    if object_type != "blob" or not object_id:
        raise RepositoryToolError(
            "not_file",
            f"Repository path is not a file at {ref}: {path}",
        )
    object_size = int(run_git(root, ["cat-file", "-s", object_id]).strip())
    if object_size > MAX_SCAN_FILE_BYTES:
        raise RepositoryToolError(
            "file_too_large",
            f"Repository file is too large at {ref}: {path}",
        )
    return subprocess.run(
        ["git", "-C", str(root), "cat-file", "blob", object_id],
        check=True,
        capture_output=True,
    ).stdout


def resolve_commit_ref(root: Path, ref: str) -> str:
    for candidate in git_ref_candidates(ref):
        try:
            return run_git(
                root,
                ["rev-parse", "--verify", "--end-of-options", f"{candidate}^{{commit}}"],
            ).strip()
        except subprocess.CalledProcessError:
            continue
    raise RepositoryToolError("ref_not_found", f"Git ref not found: {ref}")


def read_diff_window(  # noqa: PLR0913 - public bounded diff tool contract
    project_id: str,
    repository_id: str,
    *,
    path: str | None = None,
    paths: list[str] | None = None,
    base_ref: str | None = None,
    head_ref: str = "HEAD",
    offset: int = 0,
    limit: int = 16_000,
) -> RepositoryDiffWindow:
    try:
        _, repository, root = resolve_repository(project_id, repository_id)
        base = base_ref or "HEAD~1"
        args = ["diff", base, head_ref]
        if path and paths:
            raise RepositoryToolError(
                "invalid_paths",
                "Use either path or paths when reading a diff, not both.",
            )
        if path:
            validate_visible_repository_path(path)
            args.extend(["--", f":(literal){Path(path).as_posix()}"])
        elif paths:
            normalized_paths = list(dict.fromkeys(Path(item).as_posix() for item in paths))
            for selected_path in normalized_paths:
                validate_visible_repository_path(selected_path)
            args.extend(["--", *(f":(literal){item}" for item in normalized_paths)])
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
    updated = RepositoryCacheService().read_cached_repository(project.id, repository)
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


def validate_visible_repository_path(path: str) -> None:
    validate_relative_path(path)
    relative = Path(path)
    if any(part in PROFILE_SKIP_PARTS for part in relative.parts) or is_likely_secret_path(
        relative
    ):
        raise RepositoryToolError("path_filtered", f"Repository path is hidden or secret: {path}")


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
        if any(part in PROFILE_SKIP_PARTS for part in relative.parts) or is_likely_secret_path(
            relative
        ):
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
