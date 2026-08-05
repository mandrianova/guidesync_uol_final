from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from guidesync_agent.schemas import (
    CorpusExclusionReason,
    DocumentationInput,
    KnowledgeAnnotation,
    KnowledgeAnnotationEdge,
    KnowledgeAnnotationMetadata,
    KnowledgeAnnotationRun,
    KnowledgeAnnotationSourceType,
    KnowledgeChunk,
    KnowledgeConcept,
    KnowledgeEdge,
    KnowledgeEdgeType,
    KnowledgeGraphSnapshot,
    KnowledgeIndexRequest,
    KnowledgeIndexRun,
    KnowledgeIndexStatus,
    KnowledgeIndexSummary,
    KnowledgeNode,
    KnowledgeNodeKind,
    RepositoryInput,
)
from guidesync_agent.services.knowledge_annotation import AnnotationInput, annotate_sources
from guidesync_agent.services.markdown_document import split_markdown_sections
from guidesync_agent.services.repository_cache import (
    RepositoryCacheError,
    RepositoryCacheService,
    git_ref_candidates,
    run_git,
)
from guidesync_agent.services.text_normalization import tokenize_text

DOCUMENT_EXTENSIONS = {
    ".md",
    ".mdx",
    ".rst",
    ".txt",
}
DOCUMENT_FILENAMES = {"README", "README.md"}
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


class KnowledgeBuildState(BaseModel):
    run: KnowledgeIndexRun
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    edges: list[KnowledgeEdge] = Field(default_factory=list)
    chunks: list[KnowledgeChunk] = Field(default_factory=list)
    annotation_sources: list[AnnotationInput] = Field(default_factory=list)
    annotation_runs: list[KnowledgeAnnotationRun] = Field(default_factory=list)
    annotations: list[KnowledgeAnnotation] = Field(default_factory=list)
    concepts: list[KnowledgeConcept] = Field(default_factory=list)
    annotation_edges: list[KnowledgeAnnotationEdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    repositories: int = 0
    files: int = 0
    documentation_sources: int = 0


class RepositoryTextFile(BaseModel):
    relative_path: str
    text: str
    size_bytes: int
    source: str


class KnowledgeNodeInput(BaseModel):
    project_id: str | None
    repo: str | None
    kind: KnowledgeNodeKind
    name: str
    qualified_name: str
    path: str | None
    summary: str
    content_hash: str | None
    metadata: dict[str, object]
    start_line: int | None = None
    end_line: int | None = None


class KnowledgeChunkInput(BaseModel):
    project_id: str | None
    node: KnowledgeNode
    repo: str | None
    path: str
    heading: str | None
    text: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class RepositoryIndexContext:
    repository: RepositoryInput
    project_id: str | None
    repo_node: KnowledgeNode
    state: KnowledgeBuildState


@dataclass(frozen=True)
class MarkdownSectionIndexContext:
    project_id: str | None
    repo: str | None
    path: str
    parent_node: KnowledgeNode
    state: KnowledgeBuildState


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
            apply_knowledge_annotations(request, state)
        except Exception as exc:  # noqa: BLE001 - annotation should not invalidate index refs
            state.warnings.append(f"knowledge annotation failed: {exc}")
    state.run.completed_at = datetime.now(UTC)
    state.run.summary = KnowledgeIndexSummary(
        repositories=state.repositories,
        files=state.files,
        documentation_sources=state.documentation_sources,
        documents=sum(1 for node in state.nodes if node.kind == KnowledgeNodeKind.DOC_PAGE),
        sections=sum(1 for node in state.nodes if node.kind == KnowledgeNodeKind.DOC_SECTION),
        nodes=len(state.nodes),
        edges=len(state.edges),
        chunks=len(state.chunks),
        annotation_runs=len(state.annotation_runs),
        annotations=len(state.annotations),
        concepts=len(state.concepts),
        annotation_edges=len(state.annotation_edges),
        indexed_commit_sha=indexed_commit_sha(state.nodes),
        warnings=state.warnings,
    )
    state.run.source_ref = state.run.summary.indexed_commit_sha
    return KnowledgeGraphSnapshot(
        run=state.run,
        nodes=state.nodes,
        edges=state.edges,
        chunks=state.chunks,
        annotation_runs=state.annotation_runs,
        annotations=state.annotations,
        concepts=state.concepts,
        annotation_edges=state.annotation_edges,
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
        KnowledgeNodeInput(
            project_id=request.project_id,
            repo=repository.name,
            kind=KnowledgeNodeKind.REPOSITORY,
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
                "extractor": "documentation-only-repository-indexer",
            },
        )
    )
    state.nodes.append(repo_node)
    state.repositories += 1

    context = RepositoryIndexContext(
        repository=repository,
        project_id=request.project_id,
        repo_node=repo_node,
        state=state,
    )
    for file_path in iter_repository_files(root, repository, request, state.warnings):
        index_repository_file(root, file_path, context)


def index_repository_file(
    root: Path,
    file_path: Path,
    context: RepositoryIndexContext,
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
        context,
    )


def index_repository_text_file(
    file: RepositoryTextFile,
    context: RepositoryIndexContext,
) -> None:
    relative_path = file.relative_path
    text = file.text
    summary = file_summary(relative_path, text)
    commit_sha = context.repo_node.metadata.get("commit_sha")
    file_metadata: dict[str, object] = {
        "extractor": "documentation-ref-indexer",
        "source": file.source,
        "size_bytes": file.size_bytes,
        "commit_sha": commit_sha,
        "search_terms": search_terms_for(relative_path, summary),
    }
    file_node = make_node(
        KnowledgeNodeInput(
            project_id=context.project_id,
            repo=context.repository.name,
            kind=KnowledgeNodeKind.DOC_PAGE,
            name=Path(relative_path).name,
            qualified_name=f"{context.repository.name}:{relative_path}",
            path=relative_path,
            summary=summary,
            content_hash=content_hash(text),
            metadata=file_metadata,
        )
    )
    context.state.nodes.append(file_node)
    context.state.annotation_sources.append(
        AnnotationInput(
            source_type=KnowledgeAnnotationSourceType.DOC_PAGE,
            source_id=file_node.id,
            project_id=context.project_id,
            repo=context.repository.name,
            path=relative_path,
            source_commit=commit_sha if isinstance(commit_sha, str) else None,
            content_hash=file_node.content_hash,
            text=text,
            metadata=file_metadata,
        )
    )
    context.state.edges.append(
        make_edge(
            context.project_id,
            context.repo_node.id,
            file_node.id,
            KnowledgeEdgeType.CONTAINS,
            relative_path,
        )
    )
    context.state.files += 1
    index_markdown_sections(
        text,
        MarkdownSectionIndexContext(
            project_id=context.project_id,
            repo=context.repository.name,
            path=relative_path,
            parent_node=file_node,
            state=context.state,
        ),
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
        KnowledgeNodeInput(
            project_id=project_id,
            repo=None,
            kind=KnowledgeNodeKind.DOC_PAGE,
            name=document.name,
            qualified_name=path_label,
            path=path_label,
            summary=document.description or file_summary(path_label, text),
            content_hash=content_hash(text),
            metadata={"extractor": "project-documentation-indexer"},
        )
    )
    state.nodes.append(doc_node)
    state.annotation_sources.append(
        AnnotationInput(
            source_type=KnowledgeAnnotationSourceType.DOC_PAGE,
            source_id=doc_node.id,
            project_id=project_id,
            path=path_label,
            content_hash=doc_node.content_hash,
            text=text,
            metadata=doc_node.metadata,
        )
    )
    state.documentation_sources += 1
    index_markdown_sections(
        text,
        MarkdownSectionIndexContext(
            project_id=project_id,
            repo=None,
            path=path_label,
            parent_node=doc_node,
            state=state,
        ),
    )


def resolve_repository_root(repository: RepositoryInput, warnings: list[str]) -> Path | None:
    repository_path = repository.path or repository.local_path
    if repository_path is not None:
        return repository_path.expanduser().resolve()
    if repository.url is None:
        warnings.append(f"{repository.name}: repository path or URL is required")
        return None
    service = RepositoryCacheService()
    try:
        updated_repository = service.pull_or_checkout_ref(
            repository.project_id,
            service.repository_from_input(repository),
            repository.ref,
        )
    except RepositoryCacheError as exc:
        warnings.append(f"{repository.name}: repository cache checkout failed: {exc}")
        return None
    if updated_repository.local_path is None:
        warnings.append(f"{repository.name}: repository cache checkout did not return a local path")
        return None
    return Path(updated_repository.local_path).resolve()


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
        ref = RepositoryCacheService().default_branch(root) or "main"

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


def should_index_file(root: Path, path: Path, max_file_bytes: int) -> bool:
    return documentation_file_exclusion_reason(root, path, max_file_bytes) is None


def documentation_file_exclusion_reason(
    root: Path,
    path: Path,
    max_file_bytes: int,
) -> CorpusExclusionReason | None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return CorpusExclusionReason.OUTSIDE_ROOT
    if any(part in IGNORED_PARTS for part in relative.parts):
        return CorpusExclusionReason.IGNORED_PATH
    if path.is_symlink():
        return CorpusExclusionReason.SYMLINK
    if not path.is_file():
        return CorpusExclusionReason.NOT_REGULAR_FILE
    if path.stat().st_size > max_file_bytes:
        return CorpusExclusionReason.MAX_FILE_BYTES
    if not is_documentation_path(path):
        return CorpusExclusionReason.UNSUPPORTED_EXTENSION
    return None


def is_documentation_path(path: Path | str) -> bool:
    candidate = Path(path)
    return candidate.suffix.lower() in DOCUMENT_EXTENSIONS or candidate.name in DOCUMENT_FILENAMES


def index_markdown_sections(
    text: str,
    context: MarkdownSectionIndexContext,
) -> None:
    sections = split_markdown_sections(text)
    commit_sha = context.parent_node.metadata.get("commit_sha")
    for section in sections:
        title = section.title
        start_line = section.start_line
        end_line = section.end_line
        section_text = section.text
        section_summary = first_sentence(section_text)
        section_node = make_node(
            KnowledgeNodeInput(
                project_id=context.project_id,
                repo=context.repo,
                kind=KnowledgeNodeKind.DOC_SECTION,
                name=title,
                qualified_name=f"{context.path}#{title}",
                path=context.path,
                start_line=start_line,
                end_line=end_line,
                summary=section_summary,
                content_hash=content_hash(section_text),
                metadata={
                    "extractor": "markdown-section-ref-parser",
                    "commit_sha": commit_sha,
                    "line_range": [start_line, end_line],
                    "search_terms": search_terms_for(
                        context.path,
                        title,
                        section_summary,
                    ),
                },
            )
        )
        context.state.nodes.append(section_node)
        context.state.annotation_sources.append(
            AnnotationInput(
                source_type=KnowledgeAnnotationSourceType.DOC_SECTION,
                source_id=section_node.id,
                project_id=context.project_id,
                repo=context.repo,
                path=context.path,
                heading=title,
                start_line=start_line,
                end_line=end_line,
                source_commit=commit_sha if isinstance(commit_sha, str) else None,
                content_hash=section_node.content_hash,
                text=section_text,
                metadata=section_node.metadata,
            )
        )
        context.state.edges.append(
            make_edge(
                context.project_id,
                context.parent_node.id,
                section_node.id,
                KnowledgeEdgeType.CONTAINS,
                f"{context.path}:{start_line}",
            )
        )
        context.state.chunks.append(
            make_chunk(
                KnowledgeChunkInput(
                    project_id=context.project_id,
                    node=section_node,
                    repo=context.repo,
                    path=context.path,
                    heading=title,
                    text=section_reference_text(
                        title,
                        section_summary,
                        start_line,
                        end_line,
                    ),
                    metadata={
                        "extractor": "markdown-section-ref-indexer",
                        "start_line": start_line,
                        "end_line": end_line,
                        "content_hash": content_hash(section_text),
                        "commit_sha": commit_sha,
                        "search_terms": search_terms_for(
                            context.path,
                            title,
                            section_summary,
                        ),
                    },
                )
            )
        )


def markdown_sections(text: str) -> list[tuple[str, int, str]]:
    return [
        (section.title, section.start_line, section.text)
        for section in split_markdown_sections(text)
    ]


def apply_knowledge_annotations(request: KnowledgeIndexRequest, state: KnowledgeBuildState) -> None:
    bundle = annotate_sources(
        state.annotation_sources,
        taxonomy=request.taxonomy,
        taxonomy_version=request.taxonomy_version,
    )
    state.annotation_runs = bundle.annotation_runs
    state.annotations = bundle.annotations
    state.concepts = bundle.concepts
    state.annotation_edges = bundle.annotation_edges
    state.warnings.extend(bundle.warnings)

    metadata_by_source_id = bundle.metadata_by_source_id
    for node in state.nodes:
        metadata = metadata_by_source_id.get(node.id)
        if metadata is not None:
            node.metadata = merge_annotation_metadata(node.metadata, metadata)
    for chunk in state.chunks:
        metadata = metadata_by_source_id.get(chunk.node_id)
        if metadata is not None:
            chunk.metadata = merge_annotation_metadata(chunk.metadata, metadata)


def merge_annotation_metadata(
    existing: dict[str, object],
    annotation_metadata: KnowledgeAnnotationMetadata,
) -> dict[str, object]:
    merged = dict(existing)
    for key, value in annotation_metadata.model_dump(mode="python").items():
        if isinstance(value, list):
            merged[key] = merge_string_lists(
                existing.get(key),
                [item for item in value if isinstance(item, str)],
            )
        else:
            merged[key] = value
    return merged


def merge_string_lists(existing: object, incoming: list[str]) -> list[str]:
    values: list[str] = []
    if isinstance(existing, str):
        values.append(existing)
    elif isinstance(existing, list):
        values.extend(item for item in existing if isinstance(item, str))
    values.extend(incoming)
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        result.append(value)
        seen.add(key)
    return result


def indexed_commit_sha(nodes: list[KnowledgeNode]) -> str | None:
    commits = sorted(
        {
            value
            for node in nodes
            if node.kind == KnowledgeNodeKind.REPOSITORY
            and isinstance((value := node.metadata.get("commit_sha")), str)
            and value
        }
    )
    return ", ".join(commits) or None


def search_terms_for(*values: str) -> list[str]:
    terms = []
    seen: set[str] = set()
    for value in values:
        for term in tokenize_text(value):
            if len(term) < 3 or term in seen:
                continue
            terms.append(term)
            seen.add(term)
    return terms[:24]


def section_reference_text(
    title: str,
    summary: str,
    start_line: int,
    end_line: int,
) -> str:
    line_ref = f"lines {start_line}-{end_line}" if end_line > start_line else f"line {start_line}"
    if summary:
        return f"{title} ({line_ref}): {summary}"
    return f"{title} ({line_ref})"


def changed_documentation_files(
    repository: RepositoryInput,
    previous_commit: str | None,
    current_commit: str | None,
    warnings: list[str],
) -> list[str]:
    if not previous_commit or not current_commit or previous_commit == current_commit:
        return []
    root = resolve_repository_root(repository, warnings)
    if root is None:
        return []
    try:
        diff_args = ["diff", "--name-only", previous_commit, current_commit]
        if repository.paths:
            diff_args.extend(["--", *repository.paths])
        raw = run_git(root, diff_args)
    except subprocess.CalledProcessError as exc:
        warnings.append(f"{repository.name}: could not diff documentation changes: {exc.stderr}")
        return []
    return [line for line in raw.splitlines() if line and is_documentation_path(line)]


def make_node(data: KnowledgeNodeInput) -> KnowledgeNode:
    return KnowledgeNode(
        id=stable_id(
            "kg-node",
            data.project_id,
            data.repo,
            data.kind,
            data.qualified_name,
            data.start_line,
        ),
        **data.model_dump(),
    )


def make_edge(
    project_id: str | None,
    source_node_id: str,
    target_node_id: str,
    edge_type: KnowledgeEdgeType,
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


def make_chunk(data: KnowledgeChunkInput) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=stable_id(
            "kg-chunk",
            data.project_id,
            data.node.id,
            data.heading,
            content_hash(data.text),
        ),
        project_id=data.project_id,
        node_id=data.node.id,
        repo=data.repo,
        path=data.path,
        heading=data.heading,
        text=data.text,
        token_count=len(data.text.split()),
        metadata=data.metadata,
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
