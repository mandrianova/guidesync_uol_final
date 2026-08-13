from __future__ import annotations

from guidesync_agent.schemas import (
    KnowledgeAnnotationEdge,
    KnowledgeChunk,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)


def score_knowledge_text(query: str, text: str) -> float:
    from guidesync_agent.services.knowledge.retrieval import score_knowledge_text as score_text

    return score_text(query, text)


def score_knowledge_search(
    request: KnowledgeSearchRequest,
    nodes: list[KnowledgeNode],
    chunks: list[KnowledgeChunk],
    edges: list[KnowledgeEdge],
    annotation_edges: list[KnowledgeAnnotationEdge],
) -> list[KnowledgeSearchResult]:
    from guidesync_agent.services.knowledge.retrieval import (
        score_knowledge_search as score_search,
    )

    return score_search(request, nodes, chunks, edges, annotation_edges)
