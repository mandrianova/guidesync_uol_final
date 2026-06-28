from __future__ import annotations

from pathlib import Path
from typing import Any

from guidesync_agent.schemas import (
    ProjectProfileDirectoryRef,
    ProjectProfileFileListing,
    ProjectProfileFileRef,
    ProjectProfileRepositorySummary,
    ProjectProfileSnapshot,
    RepositoryCacheStatus,
    RepositoryFileWindow,
    RepositorySearchMatch,
    RepositorySearchResult,
    ToolPagination,
)
from guidesync_agent.services.project_profile_sources import (
    PROFILE_SKIP_PARTS,
    is_likely_secret_path,
)
from guidesync_agent.storage import create_project_profile_store, create_project_store
from guidesync_agent.tools.repository import (
    RepositoryToolError,
    empty_pagination,
    paginate_text,
    readable_file_text,
    resolve_repository,
    safe_repository_path,
    tool_error,
)


def get_project_profile(project_id: str) -> ProjectProfileSnapshot | None:
    return create_project_profile_store().latest(project_id)


def register_project_profile_tool(agent: Any) -> None:
    @agent.tool
    def get_project_profile_tool(project_id: str) -> dict[str, object]:
        profile = get_project_profile(project_id)
        if profile is None:
            return {
                "ok": False,
                "error": f"Project profile not found for project: {project_id}",
            }
        return {"ok": True, "profile": profile.model_dump(mode="json")}


def get_repository_summary(
    project_id: str,
    repository_id: str,
) -> ProjectProfileRepositorySummary:
    project = create_project_store().get(project_id)
    repository = (
        next((item for item in project.repositories if item.id == repository_id), None)
        if project
        else None
    )
    try:
        resolved_project, resolved_repository, root = resolve_repository(project_id, repository_id)
        return ProjectProfileRepositorySummary(
            project_id=resolved_project.id,
            repository_id=resolved_repository.id,
            name=resolved_repository.name,
            url=resolved_repository.url,
            default_branch=resolved_repository.default_branch,
            current_commit=resolved_repository.current_commit,
            cache_status=resolved_repository.cache_status,
            local_path=str(root),
            analysis_paths=resolved_repository.analysis_paths or resolved_project.analysis_paths,
            knowledge_base_path=(
                resolved_project.knowledge_base_path
                if resolved_project.knowledge_base_repository_id in {None, resolved_repository.id}
                else None
            ),
            warnings=resolved_repository.cache_warnings,
        )
    except Exception as exc:  # noqa: BLE001 - profile tools return structured summaries
        if project is None or repository is None:
            raise
        return ProjectProfileRepositorySummary(
            project_id=project.id,
            repository_id=repository.id,
            name=repository.name,
            url=repository.url,
            default_branch=repository.default_branch,
            current_commit=repository.current_commit,
            cache_status=RepositoryCacheStatus.FAILED,
            local_path=repository.local_path,
            analysis_paths=repository.analysis_paths or project.analysis_paths,
            knowledge_base_path=(
                project.knowledge_base_path
                if project.knowledge_base_repository_id in {None, repository.id}
                else None
            ),
            warnings=[tool_error(exc).message],
        )


def list_repository_profile_files(
    project_id: str,
    repository_id: str,
    *,
    path_filters: list[str] | None = None,
    offset: int = 0,
    limit: int = 400,
) -> ProjectProfileFileListing:
    safe_offset = max(0, offset)
    safe_limit = max(1, limit)
    try:
        _, repository, root = resolve_repository(project_id, repository_id)
        return list_repository_profile_files_from_root(
            project_id,
            repository.id,
            root,
            path_filters=path_filters,
            offset=safe_offset,
            limit=safe_limit,
        )
    except Exception as exc:  # noqa: BLE001 - profile tools return structured errors
        return ProjectProfileFileListing(
            ok=False,
            project_id=project_id,
            repository_id=repository_id,
            pagination=ToolPagination(offset=safe_offset, limit=safe_limit, total=0),
            error=tool_error(exc),
        )


def list_repository_profile_files_from_root(
    project_id: str,
    repository_id: str,
    root: Path,
    *,
    path_filters: list[str] | None = None,
    offset: int = 0,
    limit: int = 400,
) -> ProjectProfileFileListing:
    safe_offset = max(0, offset)
    safe_limit = max(1, limit)
    try:
        root = root.resolve()
        listing_paths = path_filters or ["."]
        entries: list[ProjectProfileDirectoryRef | ProjectProfileFileRef] = []
        resolved_paths: list[str] = []
        for path_filter in listing_paths:
            base = safe_repository_path(root, path_filter)
            if not base.exists():
                raise RepositoryToolError(
                    "not_found",
                    f"Repository path not found: {path_filter}",
                )
            if is_hidden_profile_path(root, base):
                continue
            resolved_paths.append(relative_profile_path(root, base))
            if base.is_file():
                entries.append(profile_file_ref(repository_id, root, base))
                continue
            if base.is_dir():
                entries.extend(list_profile_directory_entries(repository_id, root, base))

        entries = unique_profile_entries(entries)
        page = entries[safe_offset : safe_offset + safe_limit]
        next_offset = safe_offset + safe_limit if safe_offset + safe_limit < len(entries) else None
        return ProjectProfileFileListing(
            project_id=project_id,
            repository_id=repository_id,
            path=resolved_paths[0] if len(resolved_paths) == 1 else ".",
            directories=[
                entry for entry in page if isinstance(entry, ProjectProfileDirectoryRef)
            ],
            files=[entry for entry in page if isinstance(entry, ProjectProfileFileRef)],
            pagination=ToolPagination(
                offset=safe_offset,
                limit=safe_limit,
                total=len(entries),
                next_offset=next_offset,
                truncated=next_offset is not None,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - profile tools return structured errors
        return ProjectProfileFileListing(
            ok=False,
            project_id=project_id,
            repository_id=repository_id,
            pagination=ToolPagination(offset=safe_offset, limit=safe_limit, total=0),
            error=tool_error(exc),
        )


def list_profile_directory_entries(
    repository_id: str,
    root: Path,
    directory: Path,
) -> list[ProjectProfileDirectoryRef | ProjectProfileFileRef]:
    entries: list[ProjectProfileDirectoryRef | ProjectProfileFileRef] = []
    for child in sorted(directory.iterdir(), key=profile_entry_sort_key):
        if is_hidden_profile_path(root, child):
            continue
        if child.is_dir():
            child_directories, child_files = count_visible_direct_children(root, child)
            relative = relative_profile_path(root, child)
            entries.append(
                ProjectProfileDirectoryRef(
                    repository_id=repository_id,
                    path=relative,
                    child_directories=child_directories,
                    child_files=child_files,
                    evidence_ref=evidence_ref(repository_id, f"{relative}/"),
                )
            )
        elif child.is_file():
            entries.append(profile_file_ref(repository_id, root, child))
    return entries


def profile_file_ref(repository_id: str, root: Path, path: Path) -> ProjectProfileFileRef:
    relative = relative_profile_path(root, path)
    return ProjectProfileFileRef(
        repository_id=repository_id,
        path=relative,
        size_bytes=path.stat().st_size,
        suffix=path.suffix.lower(),
        evidence_ref=evidence_ref(repository_id, relative),
    )


def count_visible_direct_children(root: Path, directory: Path) -> tuple[int, int]:
    directories = 0
    files = 0
    for child in directory.iterdir():
        if is_hidden_profile_path(root, child):
            continue
        if child.is_dir():
            directories += 1
        elif child.is_file():
            files += 1
    return directories, files


def unique_profile_entries(
    entries: list[ProjectProfileDirectoryRef | ProjectProfileFileRef],
) -> list[ProjectProfileDirectoryRef | ProjectProfileFileRef]:
    seen: set[tuple[str, str]] = set()
    result: list[ProjectProfileDirectoryRef | ProjectProfileFileRef] = []
    for entry in entries:
        kind = "directory" if isinstance(entry, ProjectProfileDirectoryRef) else "file"
        key = (kind, entry.path)
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result


def profile_entry_sort_key(path: Path) -> tuple[bool, str]:
    return (not path.is_dir(), path.name.lower())


def is_hidden_profile_path(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in PROFILE_SKIP_PARTS for part in relative.parts) or is_likely_secret_path(
        relative
    )


def relative_profile_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return "." if relative == "." else relative


def read_repository_profile_file(
    project_id: str,
    repository_id: str,
    path: str,
    *,
    local_path: str | None = None,
    offset: int = 0,
    limit: int = 16_000,
) -> RepositoryFileWindow:
    if local_path is None:
        from guidesync_agent.tools.repository import read_file_window

        return read_file_window(project_id, repository_id, path, offset=offset, limit=limit)
    try:
        file_path = safe_repository_path(Path(local_path).resolve(), path)
        if not file_path.is_file():
            raise RepositoryToolError("not_found", f"Repository file not found: {path}")
        data = file_path.read_bytes()
        if b"\x00" in data[:4096]:
            raise RepositoryToolError("binary_file", f"Repository file appears binary: {path}")
        content, pagination = paginate_text(
            data.decode("utf-8", errors="replace"),
            offset=offset,
            limit=limit,
        )
        return RepositoryFileWindow(
            repository_id=repository_id,
            path=Path(path).as_posix(),
            content=content,
            pagination=pagination,
        )
    except Exception as exc:  # noqa: BLE001 - profile tools return structured errors
        return RepositoryFileWindow(
            ok=False,
            repository_id=repository_id,
            path=path,
            pagination=empty_pagination(offset, limit),
            error=tool_error(exc),
        )


def search_repository_profile_files(
    project_id: str,
    repository_id: str,
    query: str,
    *,
    local_path: str | None = None,
    path_filters: list[str] | None = None,
    limit: int = 20,
) -> RepositorySearchResult:
    if local_path is None:
        from guidesync_agent.tools.repository import search_repository

        return search_repository(
            project_id,
            repository_id,
            query,
            path_filters=path_filters,
            limit=limit,
        )
    try:
        needle = query.strip().lower()
        if not needle:
            return RepositorySearchResult(query=query, matches=[], total=0)
        root = Path(local_path).resolve()
        matches: list[RepositorySearchMatch] = []
        total = 0
        for file_path in iter_profile_files(root, path_filters or ["."]):
            text = readable_file_text(file_path)
            if text is None:
                continue
            relative = file_path.relative_to(root).as_posix()
            for line_number, line in enumerate(text.splitlines(), start=1):
                if needle not in line.lower():
                    continue
                total += 1
                if len(matches) < min(max(1, limit), 100):
                    matches.append(
                        RepositorySearchMatch(
                            repository_id=repository_id,
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
    except Exception as exc:  # noqa: BLE001 - profile tools return structured errors
        return RepositorySearchResult(ok=False, query=query, error=tool_error(exc))


def iter_profile_files(root: Path, path_filters: list[str]) -> list[Path]:
    candidates: list[Path] = []
    for path_filter in path_filters:
        base = safe_repository_path(root, path_filter)
        if base.is_file():
            candidates.append(base)
        elif base.is_dir():
            candidates.extend(path for path in base.rglob("*") if path.is_file())
        else:
            raise RepositoryToolError("not_found", f"Repository path not found: {path_filter}")
    selected: list[Path] = []
    for candidate in sorted(set(candidates)):
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        if any(part in PROFILE_SKIP_PARTS for part in relative.parts):
            continue
        if is_likely_secret_path(relative):
            continue
        selected.append(candidate)
    return selected


def evidence_ref(repository_id: str, path: str) -> str:
    return f"repo:{repository_id}:{Path(path).as_posix()}"
