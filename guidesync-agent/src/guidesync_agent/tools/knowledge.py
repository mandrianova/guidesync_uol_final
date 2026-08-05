from __future__ import annotations

from guidesync_agent.schemas import (
    KnowledgeDocumentRef,
    KnowledgeDocumentWindow,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    ToolPagination,
)
from guidesync_agent.storage import create_knowledge_store, create_project_store
from guidesync_agent.tools.repository import read_file_window


def search_knowledge_base(
    project_id: str,
    query: str,
    *,
    audience: str | None = None,
    taxonomy_version: str | None = None,
    tags: list[str] | None = None,
    categories: list[str] | None = None,
    keyphrases: list[str] | None = None,
    extracted_names: list[str] | None = None,
    concepts: list[str] | None = None,
    components: list[str] | None = None,
    workflows: list[str] | None = None,
    documentation_areas: list[str] | None = None,
    limit: int = 10,
) -> list[KnowledgeSearchResult]:
    search_query = " ".join(item for item in [query, audience] if item)
    return create_knowledge_store().search(
        KnowledgeSearchRequest(
            project_id=project_id,
            query=search_query,
            taxonomy_version=taxonomy_version,
            tags=tags or [],
            categories=categories or [],
            keyphrases=keyphrases or [],
            extracted_names=extracted_names or [],
            concepts=concepts or [],
            components=components or [],
            workflows=workflows or [],
            documentation_areas=documentation_areas or [],
            limit=limit,
        )
    )


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
