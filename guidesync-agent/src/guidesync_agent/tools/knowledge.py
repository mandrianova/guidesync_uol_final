from __future__ import annotations

import hashlib
import logging

from pydantic import BaseModel, Field

from guidesync_agent.schemas import (
    KnowledgeDocumentRef,
    KnowledgeDocumentWindow,
    KnowledgeNodeKind,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    ProjectConfig,
    ProjectRepository,
    ToolPagination,
)
from guidesync_agent.services.markdown_document import normalize_heading, split_markdown_sections
from guidesync_agent.services.repository_cache import RepositoryCacheService
from guidesync_agent.storage import create_knowledge_store, create_project_store
from guidesync_agent.tools.repository import (
    RepositoryToolError,
    read_file_window,
    safe_repository_path,
)

logger = logging.getLogger(__name__)


class KnowledgeBaseSearchRequest(BaseModel):
    project_id: str
    query: str
    audience: str | None = None
    taxonomy_version: str | None = None
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    keyphrases: list[str] = Field(default_factory=list)
    extracted_names: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    documentation_areas: list[str] = Field(default_factory=list)
    limit: int = 10


def search_knowledge_base(request: KnowledgeBaseSearchRequest) -> list[KnowledgeSearchResult]:
    search_query = " ".join(item for item in [request.query, request.audience] if item)
    search_limit = min(max(request.limit * 4, request.limit + 8), 50)
    results = create_knowledge_store().search(
        KnowledgeSearchRequest(
            project_id=request.project_id,
            query=search_query,
            taxonomy_version=request.taxonomy_version,
            tags=request.tags,
            categories=request.categories,
            keyphrases=request.keyphrases,
            extracted_names=request.extracted_names,
            concepts=request.concepts,
            components=request.components,
            workflows=request.workflows,
            documentation_areas=request.documentation_areas,
            limit=search_limit,
        )
    )
    project = create_project_store().get(request.project_id)
    if project is None:
        return results[: request.limit]
    current_results = [result for result in results if result_matches_checkout(project, result)]
    removed_count = len(results) - len(current_results)
    if removed_count:
        logger.info(
            "Filtered %s stale knowledge results for project %s.",
            removed_count,
            request.project_id,
        )
    return current_results[: request.limit]


def result_matches_checkout(project: ProjectConfig, result: KnowledgeSearchResult) -> bool:
    path = result.chunk.path if result.chunk and result.chunk.path else result.node.path
    if path is None:
        return True
    repository = knowledge_result_repository(project, result)
    if repository is None:
        return True
    root = RepositoryCacheService().cache_path(project.id, repository.id)
    try:
        candidate = safe_repository_path(root, path)
        markdown = candidate.read_text(encoding="utf-8", errors="replace")
    except (OSError, RepositoryToolError):
        return False
    expected_hash = result.node.content_hash
    if expected_hash is None:
        return True
    if result.node.kind is KnowledgeNodeKind.DOC_PAGE:
        matches = knowledge_content_hash(markdown) == expected_hash
    elif result.node.kind is KnowledgeNodeKind.DOC_SECTION:
        expected_heading = normalize_heading(result.node.name)
        matches = any(
            normalize_heading(section.title) == expected_heading
            and knowledge_content_hash(section.text) == expected_hash
            for section in split_markdown_sections(markdown)
        )
    else:
        matches = True
    return matches


def knowledge_result_repository(
    project: ProjectConfig,
    result: KnowledgeSearchResult,
) -> ProjectRepository | None:
    repository = next(
        (
            item
            for item in project.repositories
            if result.node.repo in {item.id, item.name}
        ),
        None,
    )
    if repository is not None:
        return repository
    if project.knowledge_base_repository_id:
        return next(
            (
                item
                for item in project.repositories
                if item.id == project.knowledge_base_repository_id
            ),
            None,
        )
    return project.repositories[0] if len(project.repositories) == 1 else None


def knowledge_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def get_knowledge_document_ref(document_id: str) -> KnowledgeDocumentRef | None:
    for project in create_project_store().list_projects():
        refs = create_knowledge_store().document_refs(project_id=project.id)
        match = next((document for document in refs.documents if document.id == document_id), None)
        if match is not None:
            return match
    return None


def read_knowledge_document_window(
    document_id: str,
    *,
    offset: int = 0,
    limit: int = 16_000,
) -> KnowledgeDocumentWindow:
    project = document_project(document_id)
    if project is None:
        return KnowledgeDocumentWindow(
            document_id=document_id,
            path="",
            pagination=ToolPagination(offset=max(0, offset), limit=max(1, limit), total=0),
        )
    project_id, repository_id, path = project
    window = read_file_window(
        project_id,
        repository_id,
        path,
        offset=offset,
        limit=limit,
    )
    return KnowledgeDocumentWindow(
        document_id=document_id,
        path=path,
        content=window.content,
        pagination=window.pagination,
        artifact_ref=window.artifact_ref,
        error=window.error,
    )


def document_project(document_id: str) -> tuple[str, str, str] | None:
    project_store = create_project_store()
    knowledge_store = create_knowledge_store()
    for project in project_store.list_projects():
        refs = knowledge_store.document_refs(project_id=project.id)
        document = next((item for item in refs.documents if item.id == document_id), None)
        if document is None:
            continue
        repository_id = project.knowledge_base_repository_id or (
            project.repositories[0].id if project.repositories else None
        )
        if repository_id is None:
            return None
        return project.id, repository_id, document.path
    return None
