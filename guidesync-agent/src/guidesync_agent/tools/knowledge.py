from __future__ import annotations

from pydantic import BaseModel, Field

from guidesync_agent.schemas import (
    KnowledgeDocumentRef,
    KnowledgeDocumentWindow,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    ToolPagination,
)
from guidesync_agent.storage import create_knowledge_store, create_project_store
from guidesync_agent.tools.repository import read_file_window


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
    return create_knowledge_store().search(
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
            limit=request.limit,
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
