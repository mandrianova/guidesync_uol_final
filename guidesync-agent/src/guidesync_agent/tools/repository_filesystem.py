from __future__ import annotations

import fnmatch
import json
import stat
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from guidesync_agent.repository_evidence_refs import (
    REPOSITORY_EVIDENCE_ROOT,
)
from guidesync_agent.repository_evidence_refs import (
    repository_evidence_ref as format_repository_evidence_ref,
)
from guidesync_agent.schemas import (
    ProjectConfig,
    ProjectProfileRepositorySummary,
    RepositoryFilesystemContext,
    RepositoryFilesystemFileInfo,
    RepositoryFilesystemResult,
    RepositoryFilesystemTreeNode,
    RepositoryVirtualRoot,
)
from guidesync_agent.services.project_profile.sources import (
    PROFILE_SKIP_PARTS,
    is_likely_secret_path,
)
from guidesync_agent.storage import create_project_store
from guidesync_agent.tools.repository import (
    MAX_SCAN_FILE_BYTES,
    RepositoryToolError,
    readable_file_text,
    resolve_repository,
    safe_repository_path,
    tool_error,
)

VIRTUAL_ROOT_PREFIX = REPOSITORY_EVIDENCE_ROOT
MAX_DIRECTORY_LIST_CHARS = 32_000
MAX_TREE_CHARS = 48_000
MAX_TREE_NODES = 1_000
MAX_SEARCH_RESULTS = 200
MAX_SEARCH_MATCHES_PER_FILE = 20
MAX_SEARCH_PREVIEW_CHARS = 240
SEARCH_TIMEOUT_SECONDS = 10
MAX_READ_FILE_CHARS = 64_000
MAX_READ_MULTIPLE_FILES = 20
MAX_READ_MULTIPLE_CHARS = 96_000


@dataclass(frozen=True)
class ResolvedVirtualPath:
    root: RepositoryVirtualRoot
    repository_root: Path
    path: Path
    relative_path: str
    virtual_path: str


@dataclass(frozen=True)
class TextReadOptions:
    head: int | None = None
    tail: int | None = None
    start_line: int | None = None
    line_count: int | None = None
    max_chars: int = MAX_READ_FILE_CHARS


def context_from_project_profile_request(request: Any) -> RepositoryFilesystemContext:
    roots = [
        virtual_root_from_profile_summary(request.project_id, repository)
        for repository in request.repositories
    ]
    return RepositoryFilesystemContext(project_id=request.project_id, roots=roots)


def context_from_project(project_id: str) -> RepositoryFilesystemContext:
    project = create_project_store().get(project_id)
    if project is None:
        raise RepositoryToolError("project_not_found", f"Project not found: {project_id}")
    return context_from_project_config(project)


def context_from_project_config(project: ProjectConfig) -> RepositoryFilesystemContext:
    return RepositoryFilesystemContext(
        project_id=project.id,
        roots=[
            RepositoryVirtualRoot(
                project_id=project.id,
                repository_id=repository.id,
                name=repository.name,
                virtual_path=virtual_root_path(repository.id),
                url=repository.url,
                default_branch=repository.default_branch or "main",
                current_commit=repository.current_commit,
                cache_status=repository.cache_status,
                local_path=repository.local_path,
                analysis_paths=repository.analysis_paths or project.analysis_paths,
                knowledge_base_path=(
                    project.knowledge_base_path
                    if project.knowledge_base_repository_id in {None, repository.id}
                    else None
                ),
                warnings=repository.cache_warnings,
            )
            for repository in project.repositories
        ],
    )


def virtual_root_from_profile_summary(
    project_id: str,
    repository: ProjectProfileRepositorySummary,
) -> RepositoryVirtualRoot:
    return RepositoryVirtualRoot(
        project_id=project_id,
        repository_id=repository.repository_id,
        name=repository.name,
        virtual_path=virtual_root_path(repository.repository_id),
        url=repository.url,
        default_branch=repository.default_branch or "main",
        current_commit=repository.current_commit,
        cache_status=repository.cache_status,
        local_path=repository.local_path,
        analysis_paths=repository.analysis_paths,
        knowledge_base_path=repository.knowledge_base_path,
        warnings=repository.warnings,
    )


def virtual_root_path(repository_id: str) -> str:
    return f"{VIRTUAL_ROOT_PREFIX}/{repository_id}/"


def list_allowed_directories(
    context: RepositoryFilesystemContext,
) -> RepositoryFilesystemResult:
    try:
        lines = ["Allowed directories:"]
        for root in context.roots:
            ref = root.current_commit or root.default_branch
            lines.append(
                f"{root.virtual_path} "
                f"(repository_id={root.repository_id}; name={root.name}; ref={ref})"
            )
        return RepositoryFilesystemResult(
            tool_name="list_allowed_directories",
            content="\n".join(lines),
            roots=context.roots,
            metadata={"root_count": len(context.roots)},
            evidence_refs=[root.virtual_path for root in context.roots],
        )
    except Exception as exc:  # noqa: BLE001 - model-facing tools return errors
        return filesystem_error("list_allowed_directories", exc)


def list_directory(
    context: RepositoryFilesystemContext,
    path: str,
) -> RepositoryFilesystemResult:
    try:
        resolved = resolve_virtual_path(context, path)
        if not resolved.path.is_dir():
            raise RepositoryToolError("not_directory", f"Not a directory: {path}")
        entries = direct_child_entries(resolved)
        lines = [f"{entry['label']} {entry['name']}" for entry in entries]
        content, truncated = bounded_lines(lines, MAX_DIRECTORY_LIST_CHARS)
        if not content:
            content = "(empty directory)"
        if truncated:
            content += "\nNarrow the path or use directory_tree on a focused subtree."
        return filesystem_result(
            "list_directory",
            resolved,
            FilesystemResultData(
                content=content,
                entries=entries,
                truncated=truncated,
                metadata={"entry_count": len(entries)},
            ),
        )
    except Exception as exc:  # noqa: BLE001 - model-facing tools return errors
        return filesystem_error("list_directory", exc, path=path)


def list_directory_with_sizes(
    context: RepositoryFilesystemContext,
    path: str,
    *,
    sort_by: str = "name",
) -> RepositoryFilesystemResult:
    try:
        resolved = resolve_virtual_path(context, path)
        if not resolved.path.is_dir():
            raise RepositoryToolError("not_directory", f"Not a directory: {path}")
        entries = direct_child_entries(resolved)
        if sort_by == "size":
            entries = sorted(
                entries,
                key=lambda entry: (
                    -int(entry["size_bytes"]),
                    str(entry["name"]).lower(),
                ),
            )
        elif sort_by != "name":
            raise RepositoryToolError(
                "invalid_sort",
                "sortBy must be either 'name' or 'size'.",
            )
        width = max([len(format_bytes(int(entry["size_bytes"]))) for entry in entries] + [1])
        lines = [
            f"{entry['label']} {format_bytes(int(entry['size_bytes'])).rjust(width)} "
            f"{entry['name']}"
            for entry in entries
        ]
        file_count = sum(1 for entry in entries if entry["type"] == "file")
        directory_count = sum(1 for entry in entries if entry["type"] == "directory")
        total_size = sum(int(entry["size_bytes"]) for entry in entries)
        lines.extend(
            [
                f"Total files: {file_count}",
                f"Total directories: {directory_count}",
                f"Combined size: {format_bytes(total_size)}",
            ]
        )
        content, truncated = bounded_lines(lines, MAX_DIRECTORY_LIST_CHARS)
        if truncated:
            content += "\nNarrow the path or use excludePatterns with directory_tree."
        return filesystem_result(
            "list_directory_with_sizes",
            resolved,
            FilesystemResultData(
                content=content,
                entries=entries,
                truncated=truncated,
                metadata={
                    "entry_count": len(entries),
                    "file_count": file_count,
                    "directory_count": directory_count,
                    "combined_size_bytes": total_size,
                    "sortBy": sort_by,
                },
            ),
        )
    except Exception as exc:  # noqa: BLE001 - model-facing tools return errors
        return filesystem_error("list_directory_with_sizes", exc, path=path)


def directory_tree(
    context: RepositoryFilesystemContext,
    path: str,
    *,
    exclude_patterns: list[str] | None = None,
) -> RepositoryFilesystemResult:
    try:
        resolved = resolve_virtual_path(context, path)
        if not resolved.path.is_dir():
            raise RepositoryToolError("not_directory", f"Not a directory: {path}")
        state = {"nodes": 0, "truncated": False}
        tree = build_tree_node(
            resolved.repository_root,
            resolved.path,
            exclude_patterns or [],
            state,
        )
        content = json.dumps(tree.model_dump(mode="json"), indent=2, ensure_ascii=False)
        truncated = bool(state["truncated"]) or len(content) > MAX_TREE_CHARS
        if len(content) > MAX_TREE_CHARS:
            content = content[:MAX_TREE_CHARS]
        if truncated:
            content += (
                "\n\nOutput truncated. Narrow path or pass excludePatterns to inspect "
                "a smaller subtree."
            )
        return RepositoryFilesystemResult(
            tool_name="directory_tree",
            content=content,
            path=resolved.virtual_path,
            repository_id=resolved.root.repository_id,
            tree=tree,
            metadata={
                "node_count": state["nodes"],
                "excludePatterns": exclude_patterns or [],
            },
            evidence_refs=[evidence_ref(resolved)],
            truncated=truncated,
        )
    except Exception as exc:  # noqa: BLE001 - model-facing tools return errors
        return filesystem_error("directory_tree", exc, path=path)


def search_files(
    context: RepositoryFilesystemContext,
    path: str,
    pattern: str,
    *,
    exclude_patterns: list[str] | None = None,
) -> RepositoryFilesystemResult:
    try:
        resolved = resolve_virtual_path(context, path, allow_filtered=True)
        if not resolved.path.exists():
            raise RepositoryToolError("not_found", f"Repository path not found: {path}")
        search_pattern = pattern.strip()
        if not search_pattern:
            raise RepositoryToolError("invalid_pattern", "Search pattern must not be empty.")
        matches, matched_files, truncated = ripgrep_search(
            resolved,
            search_pattern,
            exclude_patterns or [],
        )
        lines = [f"{match['path']}:{match['line_number']}: {match['preview']}" for match in matches]
        content = "\n".join(lines) if lines else "No matches found"
        if truncated:
            content += "\nOutput truncated. Narrow path, pattern, or excludePatterns."
        return RepositoryFilesystemResult(
            tool_name="search_files",
            content=content,
            path=resolved.virtual_path,
            repository_id=resolved.root.repository_id,
            entries=matches,
            metadata={
                "pattern": pattern,
                "backend": "ripgrep",
                "match_count": len(matches),
                "matched_file_count": matched_files,
                "excludePatterns": exclude_patterns or [],
                "max_results": MAX_SEARCH_RESULTS,
                "max_matches_per_file": MAX_SEARCH_MATCHES_PER_FILE,
            },
            evidence_refs=[str(match["evidence_ref"]) for match in matches[:20]],
            truncated=truncated,
        )
    except Exception as exc:  # noqa: BLE001 - model-facing tools return errors
        return filesystem_error("search_files", exc, path=path)


def read_text_file(
    context: RepositoryFilesystemContext,
    path: str,
    *,
    options: TextReadOptions | None = None,
) -> RepositoryFilesystemResult:
    try:
        read_options = options or TextReadOptions()
        resolved = resolve_virtual_path(context, path)
        content, truncated = read_text_content(resolved.path, read_options)
        return RepositoryFilesystemResult(
            tool_name="read_text_file",
            content=content,
            path=resolved.virtual_path,
            repository_id=resolved.root.repository_id,
            metadata={
                "relative_path": resolved.relative_path,
                "head": read_options.head,
                "tail": read_options.tail,
                "start_line": read_options.start_line,
                "line_count": read_options.line_count,
                "size_bytes": resolved.path.stat().st_size,
            },
            evidence_refs=[evidence_ref(resolved)],
            truncated=truncated,
        )
    except Exception as exc:  # noqa: BLE001 - model-facing tools return errors
        return filesystem_error("read_text_file", exc, path=path)


def read_multiple_files(
    context: RepositoryFilesystemContext,
    paths: list[str],
    *,
    max_file_chars: int = MAX_READ_FILE_CHARS,
    max_total_chars: int = MAX_READ_MULTIPLE_CHARS,
) -> RepositoryFilesystemResult:
    sections: list[str] = []
    evidence_refs: list[str] = []
    entries: list[dict[str, Any]] = []
    total_chars = 0
    truncated = False
    for path in paths[:MAX_READ_MULTIPLE_FILES]:
        try:
            resolved = resolve_virtual_path(context, path)
            content, file_truncated = read_text_content(
                resolved.path,
                TextReadOptions(max_chars=max_file_chars),
            )
            remaining = max_total_chars - total_chars
            if len(content) > remaining:
                content = content[: max(0, remaining)]
                file_truncated = True
            sections.append(f"{resolved.virtual_path}:\n{content}")
            total_chars += len(content)
            truncated = truncated or file_truncated
            evidence_refs.append(evidence_ref(resolved))
            entries.append(
                {
                    "path": resolved.virtual_path,
                    "repository_id": resolved.root.repository_id,
                    "relative_path": resolved.relative_path,
                    "truncated": file_truncated,
                }
            )
            if total_chars >= max_total_chars:
                truncated = True
                break
        except Exception as exc:  # noqa: BLE001 - per-file failures are inline
            sections.append(f"{path}:\nError: {tool_error(exc).message}")
            entries.append({"path": path, "error": tool_error(exc).model_dump()})
    if len(paths) > MAX_READ_MULTIPLE_FILES:
        truncated = True
        sections.append(
            f"Error: read_multiple_files is limited to {MAX_READ_MULTIPLE_FILES} files. "
            "Call again with a smaller paths list."
        )
    content, truncated = finalize_multiple_file_content(
        sections,
        truncated=truncated,
        max_chars=max_total_chars,
    )
    return RepositoryFilesystemResult(
        tool_name="read_multiple_files",
        content=content,
        entries=entries,
        metadata={"requested_count": len(paths), "returned_count": len(entries)},
        evidence_refs=evidence_refs,
        truncated=truncated,
    )


def get_file_info(
    context: RepositoryFilesystemContext,
    path: str,
) -> RepositoryFilesystemResult:
    try:
        resolved = resolve_virtual_path(context, path)
        info = file_info(resolved.virtual_path, resolved.path)
        lines = [
            f"path: {info.path}",
            f"name: {info.name}",
            f"type: {info.type}",
            f"size: {info.size_bytes}",
            f"permissions: {info.permissions}",
        ]
        if info.created_at is not None:
            lines.append(f"created: {info.created_at.isoformat()}")
        if info.modified_at is not None:
            lines.append(f"modified: {info.modified_at.isoformat()}")
        return RepositoryFilesystemResult(
            tool_name="get_file_info",
            content="\n".join(lines),
            path=resolved.virtual_path,
            repository_id=resolved.root.repository_id,
            file_info=info,
            metadata={"relative_path": resolved.relative_path},
            evidence_refs=[evidence_ref(resolved)],
        )
    except Exception as exc:  # noqa: BLE001 - model-facing tools return errors
        return filesystem_error("get_file_info", exc, path=path)


def ripgrep_search(
    resolved: ResolvedVirtualPath,
    pattern: str,
    exclude_patterns: list[str],
) -> tuple[list[dict[str, Any]], int, bool]:
    command = [
        "rg",
        "--json",
        "--fixed-strings",
        "--ignore-case",
        "--line-number",
        "--with-filename",
        "--color=never",
        "--hidden",
        "--no-ignore",
        "--max-filesize",
        str(MAX_SCAN_FILE_BYTES),
        "--max-count",
        str(MAX_SEARCH_MATCHES_PER_FILE),
        "--glob",
        "!.git/**",
    ]
    for pattern_to_exclude in exclude_patterns:
        if pattern_to_exclude:
            command.extend(["--glob", f"!{pattern_to_exclude}"])
    command.extend(["--", pattern, str(resolved.path)])

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=SEARCH_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RepositoryToolError(
            "ripgrep_unavailable",
            "ripgrep is required for search_files but is not installed.",
            retryable=False,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RepositoryToolError(
            "search_timeout",
            f"search_files timed out after {SEARCH_TIMEOUT_SECONDS} seconds.",
            retryable=True,
        ) from exc
    if completed.returncode not in {0, 1}:
        message = completed.stderr.strip() or "ripgrep search failed."
        raise RepositoryToolError("search_failed", message)
    return parse_ripgrep_json(resolved, completed.stdout)


def parse_ripgrep_json(
    resolved: ResolvedVirtualPath,
    output: str,
) -> tuple[list[dict[str, Any]], int, bool]:
    matches: list[dict[str, Any]] = []
    matched_files: set[str] = set()
    truncated = False
    for line in output.splitlines():
        matched_file, match = parse_ripgrep_event(resolved, line)
        if matched_file:
            matched_files.add(matched_file)
        if match is None:
            continue
        matches.append(match)
        if len(matches) >= MAX_SEARCH_RESULTS:
            truncated = True
            break
    return matches, len(matched_files), truncated


def parse_ripgrep_event(
    resolved: ResolvedVirtualPath,
    line: str,
) -> tuple[str | None, dict[str, Any] | None]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None, None
    data = event.get("data")
    if not isinstance(data, dict):
        return None, None
    if event.get("type") == "begin":
        path_text = event_path_text(data)
        visible_path = (
            path_text
            if path_text is not None and not filtered_ripgrep_path(resolved, path_text)
            else None
        )
        return visible_path, None
    if event.get("type") != "match":
        return None, None
    return None, ripgrep_match_entry(resolved, data)


def ripgrep_match_entry(
    resolved: ResolvedVirtualPath,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    path_text = event_path_text(data)
    line_number = data.get("line_number")
    lines = data.get("lines")
    if not path_text or not isinstance(line_number, int) or not isinstance(lines, dict):
        return None
    text = lines.get("text")
    if not isinstance(text, str):
        return None
    candidate = Path(path_text).resolve()
    if is_filtered_repository_path(resolved.repository_root, candidate):
        return None
    candidate_relative = relative_path(resolved.repository_root, candidate)
    return {
        "path": virtual_path_for(resolved.root, resolved.repository_root, candidate),
        "repository_id": resolved.root.repository_id,
        "relative_path": candidate_relative,
        "line_number": line_number,
        "preview": text.strip()[:MAX_SEARCH_PREVIEW_CHARS],
        "evidence_ref": format_repository_evidence_ref(
            resolved.root.repository_id,
            candidate_relative,
            line_number=line_number,
        ),
    }


def filtered_ripgrep_path(resolved: ResolvedVirtualPath, path_text: str) -> bool:
    return is_filtered_repository_path(
        resolved.repository_root,
        Path(path_text).resolve(),
    )


def event_path_text(data: dict[str, Any]) -> str | None:
    path = data.get("path")
    if not isinstance(path, dict):
        return None
    value = path.get("text")
    return value if isinstance(value, str) else None


def resolve_virtual_path(
    context: RepositoryFilesystemContext,
    path: str,
    *,
    allow_filtered: bool = False,
) -> ResolvedVirtualPath:
    if "\x00" in path:
        raise RepositoryToolError("path_outside_repository", "Invalid repository path.")
    normalized = path.replace("\\", "/").strip()
    if not normalized.startswith(f"{VIRTUAL_ROOT_PREFIX}/"):
        raise RepositoryToolError(
            "invalid_virtual_path",
            f"Path must start with {VIRTUAL_ROOT_PREFIX}/<repository_id>/: {path}",
        )
    parts = PurePosixPath(normalized).parts
    if len(parts) < 3:
        raise RepositoryToolError(
            "invalid_virtual_path",
            f"Path must include a repository id: {path}",
        )
    repository_id = parts[2]
    root = next((item for item in context.roots if item.repository_id == repository_id), None)
    if root is None:
        raise RepositoryToolError(
            "repository_not_allowed",
            f"Repository is not available in this tool context: {repository_id}",
        )
    relative = PurePosixPath(*parts[3:]).as_posix() if len(parts) > 3 else "."
    if relative in {"", "/"}:
        relative = "."
    repository_root = repository_root_path(context, root)
    resolved = safe_repository_path(repository_root, relative)
    if not allow_filtered and is_filtered_repository_path(repository_root, resolved):
        raise RepositoryToolError("path_filtered", f"Repository path is hidden or secret: {path}")
    return ResolvedVirtualPath(
        root=root,
        repository_root=repository_root,
        path=resolved,
        relative_path=relative_path(repository_root, resolved),
        virtual_path=virtual_path_for(root, repository_root, resolved),
    )


def repository_root_path(
    context: RepositoryFilesystemContext,
    root: RepositoryVirtualRoot,
) -> Path:
    if root.local_path:
        return Path(root.local_path).resolve()
    _, resolved_repository, path = resolve_repository(context.project_id, root.repository_id)
    root.current_commit = resolved_repository.current_commit
    root.cache_status = resolved_repository.cache_status
    return path


def direct_child_entries(resolved: ResolvedVirtualPath) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for child in sorted(
        resolved.path.iterdir(),
        key=lambda item: (not item.is_dir(), item.name.lower()),
    ):
        if is_filtered_repository_path(resolved.repository_root, child):
            continue
        child_type = "directory" if child.is_dir() else "file"
        child_relative = relative_path(resolved.repository_root, child)
        entries.append(
            {
                "name": child.name,
                "type": child_type,
                "label": "[DIR]" if child_type == "directory" else "[FILE]",
                "path": virtual_path_for(resolved.root, resolved.repository_root, child),
                "relative_path": child_relative,
                "size_bytes": path_size(child),
                "evidence_ref": format_repository_evidence_ref(
                    resolved.root.repository_id,
                    child_relative,
                    is_directory=child_type == "directory",
                ),
            }
        )
    return entries


def build_tree_node(
    root: Path,
    path: Path,
    exclude_patterns: list[str],
    state: dict[str, Any],
) -> RepositoryFilesystemTreeNode:
    state["nodes"] = int(state["nodes"]) + 1
    node_type = "directory" if path.is_dir() else "file"
    node = RepositoryFilesystemTreeNode(name=path.name or path.as_posix(), type=node_type)
    if node_type == "file":
        return node
    children: list[RepositoryFilesystemTreeNode] = []
    for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if int(state["nodes"]) >= MAX_TREE_NODES:
            state["truncated"] = True
            break
        if is_filtered_repository_path(root, child):
            continue
        if matches_exclude_patterns(root, child, exclude_patterns):
            continue
        children.append(build_tree_node(root, child, exclude_patterns, state))
    node.children = children
    return node


def iter_visible_paths(root: Path, base: Path, exclude_patterns: list[str]) -> list[Path]:
    candidates = [base]
    if base.is_dir():
        candidates.extend(base.rglob("*"))
    visible = []
    for candidate in candidates:
        if is_filtered_repository_path(root, candidate):
            continue
        if matches_exclude_patterns(root, candidate, exclude_patterns):
            continue
        visible.append(candidate)
    return sorted(set(visible), key=lambda item: relative_path(root, item).lower())


def finalize_multiple_file_content(
    sections: list[str],
    *,
    truncated: bool,
    max_chars: int,
) -> tuple[str, bool]:
    content = "\n---\n".join(sections)
    if truncated:
        content += "\n---\nOutput truncated. Read fewer files or use focused windows."
    return bounded_text(content, max_chars=max_chars, truncated=truncated)


def read_text_content(path: Path, options: TextReadOptions) -> tuple[str, bool]:
    validate_text_read_options(options)
    if not path.is_file():
        raise RepositoryToolError("not_file", f"Not a text file: {path.name}")
    text = readable_file_text(path)
    if text is None:
        raise RepositoryToolError("binary_file", f"Repository file appears binary: {path.name}")
    selected, truncated = select_text_window(text, options)
    return bounded_text(selected, max_chars=options.max_chars, truncated=truncated)


def validate_text_read_options(options: TextReadOptions) -> None:
    if options.head is not None and options.tail is not None:
        raise RepositoryToolError("invalid_read_window", "head and tail cannot both be specified.")
    line_window_requested = options.start_line is not None or options.line_count is not None
    if line_window_requested and (options.head is not None or options.tail is not None):
        raise RepositoryToolError(
            "invalid_read_window",
            "startLine/lineCount cannot be combined with head or tail.",
        )
    if options.max_chars < 1:
        raise RepositoryToolError("invalid_read_limit", "max_chars must be positive.")


def select_text_window(text: str, options: TextReadOptions) -> tuple[str, bool]:
    if options.head is not None:
        safe_head = max(0, options.head)
        lines = text.splitlines(keepends=True)
        return "".join(lines[:safe_head]), safe_head < len(lines)
    if options.tail is not None:
        safe_tail = max(0, options.tail)
        lines = text.splitlines(keepends=True)
        return "".join(lines[-safe_tail:]) if safe_tail else "", safe_tail < len(lines)
    if options.start_line is not None or options.line_count is not None:
        safe_start = max(1, options.start_line or 1)
        safe_count = max(1, options.line_count or 200)
        lines = text.splitlines(keepends=True)
        first_index = safe_start - 1
        last_index = first_index + safe_count
        return (
            "".join(lines[first_index:last_index]),
            first_index > 0 or last_index < len(lines),
        )
    return text, False


def bounded_text(text: str, *, max_chars: int, truncated: bool) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, truncated
    notice = "\n\nOutput truncated. Request a focused head, tail, or line window."
    prefix_limit = max(0, max_chars - len(notice))
    return f"{text[:prefix_limit]}{notice}"[:max_chars], True


def file_info(path: str, filesystem_path: Path) -> RepositoryFilesystemFileInfo:
    raw = filesystem_path.stat()
    return RepositoryFilesystemFileInfo(
        path=path,
        name=filesystem_path.name,
        type="directory" if filesystem_path.is_dir() else "file",
        size_bytes=path_size(filesystem_path),
        created_at=datetime.fromtimestamp(raw.st_ctime, tz=UTC),
        modified_at=datetime.fromtimestamp(raw.st_mtime, tz=UTC),
        permissions=stat.filemode(raw.st_mode),
    )


def matches_exclude_patterns(root: Path, path: Path, patterns: list[str]) -> bool:
    relative = relative_path(root, path)
    name = path.name
    return any(
        fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(relative, pattern) for pattern in patterns
    )


def is_filtered_repository_path(root: Path, path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    if relative == Path("."):
        return False
    return any(part in PROFILE_SKIP_PARTS for part in relative.parts) or is_likely_secret_path(
        relative
    )


def relative_path(root: Path, path: Path) -> str:
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    return "." if relative == "." else relative


def virtual_path_for(root: RepositoryVirtualRoot, repository_root: Path, path: Path) -> str:
    relative = relative_path(repository_root, path)
    if relative == ".":
        return root.virtual_path
    return f"{root.virtual_path}{relative}"


def evidence_ref(resolved: ResolvedVirtualPath) -> str:
    return format_repository_evidence_ref(
        resolved.root.repository_id,
        resolved.relative_path,
        is_directory=resolved.path.is_dir(),
    )


def path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return 0


def format_bytes(size: int) -> str:
    return f"{size} B"


def bounded_lines(lines: list[str], max_chars: int) -> tuple[str, bool]:
    selected: list[str] = []
    total = 0
    for line in lines:
        next_total = total + len(line) + 1
        if next_total > max_chars:
            return "\n".join(selected), True
        selected.append(line)
        total = next_total
    return "\n".join(selected), False


@dataclass(frozen=True)
class FilesystemResultData:
    content: str
    entries: list[dict[str, Any]]
    truncated: bool
    metadata: dict[str, Any]


def filesystem_result(
    tool_name: str,
    resolved: ResolvedVirtualPath,
    data: FilesystemResultData,
) -> RepositoryFilesystemResult:
    return RepositoryFilesystemResult(
        tool_name=tool_name,
        content=data.content,
        path=resolved.virtual_path,
        repository_id=resolved.root.repository_id,
        entries=data.entries,
        metadata=data.metadata,
        evidence_refs=[entry["evidence_ref"] for entry in data.entries[:20]],
        truncated=data.truncated,
    )


def filesystem_error(
    tool_name: str,
    exc: Exception,
    *,
    path: str | None = None,
) -> RepositoryFilesystemResult:
    error = tool_error(exc)
    return RepositoryFilesystemResult(
        tool_name=tool_name,
        content=f"Error: {error.message}",
        path=path,
        error=error,
    )
