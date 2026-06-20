from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from guidesync_agent.evidence import (
    cached_default_branch,
    ensure_github_repository_cache,
    github_owner_repo,
    run_git,
)
from guidesync_agent.knowledge_parsers import ParsedFile, parse_code_file
from guidesync_agent.knowledge_tagging import TaggableDocument, TaggingResult, tag_documents
from guidesync_agent.schemas import (
    DocumentationInput,
    KnowledgeChunk,
    KnowledgeEdge,
    KnowledgeGraphSnapshot,
    KnowledgeIndexRequest,
    KnowledgeIndexRun,
    KnowledgeIndexStatus,
    KnowledgeIndexSummary,
    KnowledgeNode,
    RepositoryInput,
)

TEXT_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".mdx",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
CONFIG_FILENAMES = {
    "Dockerfile",
    "Makefile",
    "package.json",
    "pyproject.toml",
    "README",
    "README.md",
    "tsconfig.json",
}
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "outputs",
    "var",
}


@dataclass
class KnowledgeBuildState:
    run: KnowledgeIndexRun
    nodes: list[KnowledgeNode] = field(default_factory=list)
    edges: list[KnowledgeEdge] = field(default_factory=list)
    chunks: list[KnowledgeChunk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    repositories: int = 0
    files: int = 0
    documentation_sources: int = 0


@dataclass(frozen=True)
class RepositoryTextFile:
    relative_path: str
    text: str
    size_bytes: int
    source: str


def build_knowledge_snapshot(request: KnowledgeIndexRequest) -> KnowledgeGraphSnapshot:
    now = datetime.now(UTC)
    run = KnowledgeIndexRun(
        project_id=request.project_id,
        status=KnowledgeIndexStatus.RUNNING,
        started_at=now,
        request=request,
    )
    state = KnowledgeBuildState(run=run)
    try:
        for repository in request.repositories:
            index_repository(repository, request, state)
        for document in request.documentation:
            index_document_input(document, request.project_id, state)
        state.run.status = KnowledgeIndexStatus.COMPLETED
    except Exception as exc:  # noqa: BLE001 - the run record should preserve failures
        state.run.status = KnowledgeIndexStatus.FAILED
        state.run.error_message = str(exc)
        state.warnings.append(str(exc))
    if state.nodes or state.chunks:
        try:
            apply_knowledge_tags(state)
        except Exception as exc:  # noqa: BLE001 - tagging should not invalidate indexed evidence
            state.warnings.append(f"knowledge tagging failed: {exc}")
    state.run.completed_at = datetime.now(UTC)
    state.run.summary = KnowledgeIndexSummary(
        repositories=state.repositories,
        files=state.files,
        documentation_sources=state.documentation_sources,
        nodes=len(state.nodes),
        edges=len(state.edges),
        chunks=len(state.chunks),
        warnings=state.warnings,
    )
    state.run.source_ref = ", ".join(
        sorted(
            {
                node.metadata.get("commit_sha", "")
                for node in state.nodes
                if node.kind == "repository" and node.metadata.get("commit_sha")
            }
        )
    ) or None
    return KnowledgeGraphSnapshot(
        run=state.run,
        nodes=state.nodes,
        edges=state.edges,
        chunks=state.chunks,
    )


def index_repository(
    repository: RepositoryInput,
    request: KnowledgeIndexRequest,
    state: KnowledgeBuildState,
) -> None:
    root = resolve_repository_root(repository, state.warnings)
    if root is None:
        return
    commit_sha = git_head(root)
    repo_ref = repository.url or str(root)
    repo_node = make_node(
        project_id=request.project_id,
        repo=repository.name,
        kind="repository",
        name=repository.name,
        qualified_name=repo_ref,
        path=None,
        summary=f"Repository indexed from {repo_ref}.",
        content_hash=content_hash(repo_ref),
        metadata={
            "source": repo_ref,
            "ref": repository.ref,
            "commit_sha": commit_sha,
            "paths": repository.paths,
            "extractor": "repository-indexer",
        },
    )
    state.nodes.append(repo_node)
    state.repositories += 1

    if state.files >= request.max_files:
        return

    for file_path in iter_repository_files(root, repository, request, state.warnings):
        index_repository_file(root, file_path, repository, request.project_id, repo_node, state)
        if state.files >= request.max_files:
            break


def index_repository_file(
    root: Path,
    file_path: Path,
    repository: RepositoryInput,
    project_id: str | None,
    repo_node: KnowledgeNode,
    state: KnowledgeBuildState,
) -> None:
    relative_path = file_path.relative_to(root).as_posix()
    text = read_text(file_path)
    if text is None:
        return
    index_repository_text_file(
        RepositoryTextFile(
            relative_path=relative_path,
            text=text,
            size_bytes=file_path.stat().st_size,
            source=str(file_path),
        ),
        repository,
        project_id,
        repo_node,
        state,
    )


def index_repository_text_file(
    file: RepositoryTextFile,
    repository: RepositoryInput,
    project_id: str | None,
    repo_node: KnowledgeNode,
    state: KnowledgeBuildState,
) -> None:
    relative_path = file.relative_path
    text = file.text
    file_kind = classify_file(relative_path)
    parsed_file = None if file_kind == "doc_page" else parse_code_file(relative_path, text)
    file_metadata: dict[str, object] = {
        "extractor": "repository-file-indexer",
        "source": file.source,
        "size_bytes": file.size_bytes,
    }
    if parsed_file is not None:
        file_metadata.update(parser_metadata(parsed_file))
    file_node = make_node(
        project_id=project_id,
        repo=repository.name,
        kind=file_kind,
        name=Path(relative_path).name,
        qualified_name=f"{repository.name}:{relative_path}",
        path=relative_path,
        summary=file_summary(relative_path, text),
        content_hash=content_hash(text),
        metadata=file_metadata,
    )
    state.nodes.append(file_node)
    state.edges.append(make_edge(project_id, repo_node.id, file_node.id, "contains", relative_path))
    state.files += 1

    if file_kind == "doc_page":
        index_markdown_sections(project_id, repository.name, relative_path, text, file_node, state)
    else:
        if parsed_file is None:
            return
        state.chunks.append(
            make_chunk(
                project_id=project_id,
                node=file_node,
                repo=repository.name,
                path=relative_path,
                heading=None,
                text=truncate_text(text),
                metadata={
                    "extractor": "file-text-chunker",
                    **parser_metadata(parsed_file),
                },
            )
        )
        index_code_symbols(
            project_id,
            repository.name,
            relative_path,
            parsed_file,
            file_node,
            state,
        )


def index_document_input(
    document: DocumentationInput,
    project_id: str | None,
    state: KnowledgeBuildState,
) -> None:
    text = document.content
    path_label = str(document.path) if document.path else f"project-docs/{document.name}"
    if text is None and document.path is not None and document.path.exists():
        text = document.path.read_text(encoding="utf-8", errors="replace")
    if not text:
        state.warnings.append(f"{document.name}: documentation source is empty")
        return
    doc_node = make_node(
        project_id=project_id,
        repo=None,
        kind="doc_page",
        name=document.name,
        qualified_name=path_label,
        path=path_label,
        summary=document.description or file_summary(path_label, text),
        content_hash=content_hash(text),
        metadata={"extractor": "project-documentation-indexer"},
    )
    state.nodes.append(doc_node)
    state.documentation_sources += 1
    index_markdown_sections(project_id, None, path_label, text, doc_node, state)


def resolve_repository_root(repository: RepositoryInput, warnings: list[str]) -> Path | None:
    if repository.path is not None:
        return repository.path.expanduser().resolve()
    if repository.url is None:
        warnings.append(f"{repository.name}: repository path or URL is required")
        return None
    owner_repo = github_owner_repo(repository.url)
    if owner_repo is None:
        warnings.append(f"{repository.name}: only GitHub repository URLs are supported")
        return None
    owner, repo = owner_repo
    root = ensure_github_repository_cache(repository.url, owner, repo).resolve()
    checkout_repository_ref(root, repository, warnings)
    return root


def iter_repository_files(
    root: Path,
    repository: RepositoryInput,
    request: KnowledgeIndexRequest,
    warnings: list[str],
) -> Iterable[Path]:
    if not root.exists():
        warnings.append(f"{repository.name}: repository root does not exist: {root}")
        return []
    candidates: list[Path] = []
    path_filters = repository.paths or ["."]
    for path_filter in path_filters:
        candidate = (root / path_filter).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            warnings.append(f"{repository.name}: skipped path outside repository: {path_filter}")
            continue
        if candidate.is_file():
            candidates.append(candidate)
        elif candidate.is_dir():
            candidates.extend(path for path in candidate.rglob("*") if path.is_file())
        else:
            warnings.append(f"{repository.name}: path filter not found: {path_filter}")
    selected = []
    for candidate in sorted(set(candidates)):
        if len(selected) >= request.max_files:
            break
        if should_index_file(root, candidate, request.max_file_bytes):
            selected.append(candidate)
    return selected


def checkout_repository_ref(
    root: Path,
    repository: RepositoryInput,
    warnings: list[str],
) -> None:
    ref = repository.ref.strip() if repository.ref else "HEAD"
    if ref == "HEAD":
        default_branch, default_warning = cached_default_branch(root)
        if default_warning:
            warnings.append(f"{repository.name}: {default_warning}")
        ref = default_branch or "main"

    last_error = ""
    for candidate in git_ref_candidates(ref):
        try:
            run_git(root, ["rev-parse", "--verify", candidate])
            run_git(
                root,
                [
                    "-c",
                    "filter.lfs.smudge=",
                    "-c",
                    "filter.lfs.process=",
                    "-c",
                    "filter.lfs.required=false",
                    "checkout",
                    "--force",
                    "--detach",
                    candidate,
                ],
            )
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc.stderr.strip()
            continue
    message = f"{repository.name}: git ref not found for knowledge index: {ref}"
    if last_error:
        message = f"{message} ({last_error})"
    warnings.append(message)


def git_ref_candidates(ref: str) -> list[str]:
    if ref.startswith(("origin/", "refs/")) or re.fullmatch(r"[0-9a-fA-F]{7,40}", ref):
        return [ref]
    return [f"origin/{ref}", ref]


def should_index_file(root: Path, path: Path, max_file_bytes: int) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    if any(part in IGNORED_PARTS for part in relative.parts):
        return False
    if path.is_symlink() or not path.is_file():
        return False
    if path.stat().st_size > max_file_bytes:
        return False
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name in CONFIG_FILENAMES


def classify_file(relative_path: str) -> str:
    path = Path(relative_path)
    lower = relative_path.lower()
    if path.suffix.lower() in {".md", ".mdx", ".rst", ".txt"} or "readme" in lower:
        return "doc_page"
    if path.name in CONFIG_FILENAMES or path.suffix.lower() in {".json", ".toml", ".yaml", ".yml"}:
        return "config"
    return "file"


def index_markdown_sections(
    project_id: str | None,
    repo: str | None,
    path: str,
    text: str,
    parent_node: KnowledgeNode,
    state: KnowledgeBuildState,
) -> None:
    sections = markdown_sections(text)
    for title, start_line, section_text in sections:
        section_node = make_node(
            project_id=project_id,
            repo=repo,
            kind="doc_section",
            name=title,
            qualified_name=f"{path}#{title}",
            path=path,
            start_line=start_line,
            end_line=start_line + max(section_text.count("\n"), 0),
            summary=first_sentence(section_text),
            content_hash=content_hash(section_text),
            metadata={"extractor": "markdown-section-parser"},
        )
        state.nodes.append(section_node)
        state.edges.append(
            make_edge(
                project_id,
                parent_node.id,
                section_node.id,
                "contains",
                f"{path}:{start_line}",
            )
        )
        state.chunks.append(
            make_chunk(
                project_id=project_id,
                node=section_node,
                repo=repo,
                path=path,
                heading=title,
                text=truncate_text(section_text),
                metadata={"extractor": "markdown-section-chunker", "start_line": start_line},
            )
        )


def markdown_sections(text: str) -> list[tuple[str, int, str]]:
    lines = text.splitlines()
    headings: list[tuple[str, int]] = []
    for index, line in enumerate(lines, start=1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            headings.append((match.group(2).strip(), index))
    if not headings:
        return [("Document", 1, text)]
    sections: list[tuple[str, int, str]] = []
    for current_index, (title, start_line) in enumerate(headings):
        next_start = (
            headings[current_index + 1][1]
            if current_index + 1 < len(headings)
            else len(lines) + 1
        )
        section_text = "\n".join(lines[start_line - 1 : next_start - 1])
        sections.append((title, start_line, section_text))
    return sections


def index_code_symbols(
    project_id: str | None,
    repo: str | None,
    path: str,
    parsed_file: ParsedFile,
    parent_node: KnowledgeNode,
    state: KnowledgeBuildState,
) -> None:
    for warning in parsed_file.warnings:
        state.warnings.append(f"{path}: {warning}")
    for symbol in parsed_file.symbols:
        symbol_node = make_node(
            project_id=project_id,
            repo=repo,
            kind="symbol",
            name=symbol.name,
            qualified_name=f"{path}:{symbol.name}",
            path=path,
            start_line=symbol.line_number,
            end_line=symbol.line_number,
            summary=symbol.source_line,
            content_hash=content_hash(f"{path}:{symbol.line_number}:{symbol.source_line}"),
            metadata={
                "extractor": parsed_file.parser_name,
                "parser": parsed_file.parser_name,
                "language": parsed_file.language,
                "symbol_kind": symbol.symbol_kind,
                **symbol.metadata,
            },
        )
        state.nodes.append(symbol_node)
        state.edges.append(
            make_edge(
                project_id,
                parent_node.id,
                symbol_node.id,
                "contains",
                f"{path}:{symbol.line_number}",
            )
        )


def parser_metadata(parsed_file: ParsedFile) -> dict[str, object]:
    return {
        "parser": parsed_file.parser_name,
        "language": parsed_file.language,
        "symbol_count": len(parsed_file.symbols),
        "import_count": len(parsed_file.imports),
        "export_count": len(parsed_file.exports),
        "imports": [item.module for item in parsed_file.imports],
        "exports": parsed_file.exports,
    }


def apply_knowledge_tags(state: KnowledgeBuildState) -> None:
    node_by_id = {node.id: node for node in state.nodes}
    documents: list[TaggableDocument] = []
    for node in state.nodes:
        documents.append(
            TaggableDocument(
                id=f"node:{node.id}",
                title=node.name,
                path=node.path,
                kind=node.kind,
                text=" ".join(
                    item
                    for item in [node.qualified_name, node.summary]
                    if item
                ),
                metadata=node.metadata,
            )
        )
    for chunk in state.chunks:
        parent_node = node_by_id.get(chunk.node_id)
        documents.append(
            TaggableDocument(
                id=f"chunk:{chunk.id}",
                title=chunk.heading or (parent_node.name if parent_node else chunk.path or "chunk"),
                path=chunk.path,
                kind="chunk",
                text=" ".join(
                    item
                    for item in [
                        parent_node.name if parent_node else None,
                        parent_node.summary if parent_node else None,
                        chunk.text,
                    ]
                    if item
                ),
                metadata=chunk.metadata,
            )
        )

    results = tag_documents(documents)
    for node in state.nodes:
        result = results.get(f"node:{node.id}")
        if result is None:
            continue
        node.metadata = tagged_metadata(node.metadata, result)
    for chunk in state.chunks:
        result = results.get(f"chunk:{chunk.id}")
        if result is None:
            continue
        chunk.metadata = tagged_metadata(chunk.metadata, result)


def tagged_metadata(metadata: dict[str, object], result: TaggingResult) -> dict[str, object]:
    return {
        **metadata,
        "tags": result.tags,
        "categories": result.categories,
        "tagger": "tfidf-v1",
        "tag_token_count": result.token_count,
    }


def make_node(
    *,
    project_id: str | None,
    repo: str | None,
    kind: str,
    name: str,
    qualified_name: str,
    path: str | None,
    summary: str,
    content_hash: str | None,
    metadata: dict[str, object],
    start_line: int | None = None,
    end_line: int | None = None,
) -> KnowledgeNode:
    return KnowledgeNode(
        id=stable_id("kg-node", project_id, repo, kind, qualified_name, start_line),
        project_id=project_id,
        repo=repo,
        kind=kind,
        name=name,
        qualified_name=qualified_name,
        path=path,
        start_line=start_line,
        end_line=end_line,
        summary=summary,
        content_hash=content_hash,
        metadata=metadata,
    )


def make_edge(
    project_id: str | None,
    source_node_id: str,
    target_node_id: str,
    edge_type: str,
    evidence_ref: str | None,
) -> KnowledgeEdge:
    return KnowledgeEdge(
        id=stable_id("kg-edge", project_id, source_node_id, target_node_id, edge_type),
        project_id=project_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_type=edge_type,
        evidence_ref=evidence_ref,
        metadata={"extractor": "repository-indexer"},
    )


def make_chunk(
    *,
    project_id: str | None,
    node: KnowledgeNode,
    repo: str | None,
    path: str,
    heading: str | None,
    text: str,
    metadata: dict[str, object],
) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=stable_id("kg-chunk", project_id, node.id, heading, content_hash(text)),
        project_id=project_id,
        node_id=node.id,
        repo=repo,
        path=path,
        heading=heading,
        text=text,
        token_count=len(text.split()),
        metadata=metadata,
    )


def stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def git_head(root: Path) -> str | None:
    if not (root / ".git").exists():
        return None
    try:
        return run_git(root, ["rev-parse", "HEAD"]).strip()
    except Exception:  # noqa: BLE001 - missing git metadata should not fail indexing
        return None


def file_summary(path: str, text: str) -> str:
    first = first_sentence(text)
    return f"{path}: {first}" if first else path


def first_sentence(text: str) -> str:
    compact = " ".join(text.strip().split())
    if not compact:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", compact, maxsplit=1)[0]
    return sentence[:240]


def truncate_text(text: str, limit: int = 4_000) -> str:
    compact = text.strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1]}..."
