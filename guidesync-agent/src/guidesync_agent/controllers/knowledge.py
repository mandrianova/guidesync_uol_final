from __future__ import annotations

from guidesync_agent.knowledge import build_knowledge_snapshot
from guidesync_agent.schemas import (
    DocumentationInput,
    KnowledgeContextPack,
    KnowledgeContextPackRequest,
    KnowledgeIndexRequest,
    KnowledgeIndexRun,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    ProjectConfig,
    RepositoryInput,
)
from guidesync_agent.storage import create_knowledge_store, create_project_store


class KnowledgeProjectNotFoundError(ValueError):
    pass


class KnowledgeIndexRequestError(ValueError):
    pass


def create_index_run(request: KnowledgeIndexRequest) -> KnowledgeIndexRun:
    prepared = prepare_index_request(request)
    if not prepared.repositories and not prepared.documentation:
        raise KnowledgeIndexRequestError(
            "At least one repository or documentation source is required."
        )
    snapshot = build_knowledge_snapshot(prepared)
    create_knowledge_store().save_snapshot(snapshot)
    return snapshot.run


def list_index_runs(project_id: str | None = None) -> list[KnowledgeIndexRun]:
    return create_knowledge_store().list_index_runs(project_id=project_id)


def get_index_run(run_id: str) -> KnowledgeIndexRun | None:
    return create_knowledge_store().get_index_run(run_id)


def search(request: KnowledgeSearchRequest) -> list[KnowledgeSearchResult]:
    return create_knowledge_store().search(request)


def context_pack(request: KnowledgeContextPackRequest) -> KnowledgeContextPack:
    search_request = KnowledgeSearchRequest(
        query=request.goal,
        project_id=request.project_id,
        kinds=request.kinds,
        path_prefixes=request.path_prefixes,
        limit=request.limit,
    )
    results = trim_results_to_budget(create_knowledge_store().search(search_request), request)
    node_ids = {result.node.id for result in results}
    nodes = list({result.node.id: result.node for result in results}.values())
    edges = create_knowledge_store().related_edges(node_ids, project_id=request.project_id)
    return KnowledgeContextPack(
        goal=request.goal,
        results=results,
        nodes=nodes,
        edges=edges,
    )


def prepare_index_request(request: KnowledgeIndexRequest) -> KnowledgeIndexRequest:
    if request.project_id is None:
        return request
    project = create_project_store().get(request.project_id)
    if project is None:
        raise KnowledgeProjectNotFoundError(f"Project not found: {request.project_id}")
    return request.model_copy(
        update={
            "repositories": [*repositories_from_project(project), *request.repositories],
            "documentation": [*documentation_from_project(project), *request.documentation],
        }
    )


def repositories_from_project(project: ProjectConfig) -> list[RepositoryInput]:
    return [
        RepositoryInput(
            name=repository.name,
            url=repository.url,
            ref=repository.default_branch or "HEAD",
            paths=repository.paths,
        )
        for repository in project.repositories
    ]


def documentation_from_project(project: ProjectConfig) -> list[DocumentationInput]:
    return [
        DocumentationInput(
            name=document.name,
            description=document.description,
            content=document.content,
        )
        for document in project.documentation
    ]


def trim_results_to_budget(
    results: list[KnowledgeSearchResult],
    request: KnowledgeContextPackRequest,
) -> list[KnowledgeSearchResult]:
    selected: list[KnowledgeSearchResult] = []
    used_tokens = 0
    for result in results:
        text = result.chunk.text if result.chunk is not None else result.matched_text
        next_tokens = max(len(text.split()), 1)
        if selected and used_tokens + next_tokens > request.token_budget:
            break
        selected.append(result)
        used_tokens += next_tokens
    return selected
