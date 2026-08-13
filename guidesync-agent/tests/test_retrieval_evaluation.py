from __future__ import annotations

from guidesync_agent.schemas import (
    KnowledgeAnnotationEdge,
    KnowledgeAnnotationEdgeType,
    KnowledgeAnnotationItemMetadata,
    KnowledgeAnnotationSourceType,
    KnowledgeAnnotationTargetType,
    KnowledgeChunk,
    KnowledgeNode,
    KnowledgeNodeKind,
    RetrievalEvaluationCase,
    RetrievalEvaluationStrategy,
)
from guidesync_agent.services.evaluation.retrieval import evaluate_retrieval


def test_retrieval_evaluation_compares_lexical_and_taxonomy_graph_ranking() -> None:  # noqa: PLR0915
    model_section = section_node(
        "section-model-settings",
        "Model settings",
        "docs/model-settings.md",
        {
            "categories": ["model-configuration"],
            "concepts": ["configure model", "model profile"],
            "keyphrases": ["model profile"],
            "extracted_names": ["ModelSettingsPage"],
            "taxonomy_version": "profile-1:v1",
            "embedding_score": 25.0,
            "embedding_model_id": "local-fixture-embedding",
        },
    )
    lexical_section = section_node(
        "section-provider-keywords",
        "Provider keywords",
        "docs/provider-keywords.md",
        {},
    )
    chunks = [
        chunk_for(model_section, "Use this page to configure the model profile."),
        chunk_for(
            lexical_section,
            "Provider settings provider settings provider settings provider settings.",
        ),
    ]

    report = evaluate_retrieval(
        cases=[
            RetrievalEvaluationCase(
                id="model-profile-from-provider-settings",
                query="provider settings",
                expected_top_paths=["docs/model-settings.md"],
                relevance_grades={"docs/model-settings.md": 3.0},
                taxonomy_version="profile-1:v1",
                categories=["model-configuration"],
                keyphrases=["model profile"],
                components=["ModelSettingsPage"],
                workflows=["configure model"],
            )
        ],
        nodes=[model_section, lexical_section],
        chunks=chunks,
        edges=[],
        annotation_edges=[
            annotation_edge(
                source_id=model_section.id,
                edge_type=KnowledgeAnnotationEdgeType.DESCRIBES_COMPONENT,
                target_type=KnowledgeAnnotationTargetType.COMPONENT,
                target_value="ModelSettingsPage",
            ),
            annotation_edge(
                source_id=model_section.id,
                edge_type=KnowledgeAnnotationEdgeType.COVERS_WORKFLOW,
                target_type=KnowledgeAnnotationTargetType.WORKFLOW,
                target_value="configure model",
            ),
        ],
        include_embedding_ablation=True,
    )

    results = {(result.case_id, result.strategy): result for result in report.results}
    lexical = results[("model-profile-from-provider-settings", RetrievalEvaluationStrategy.LEXICAL)]
    full = results[
        ("model-profile-from-provider-settings", RetrievalEvaluationStrategy.TAXONOMY_GRAPH)
    ]
    embedding = results[
        ("model-profile-from-provider-settings", RetrievalEvaluationStrategy.LEXICAL_EMBEDDING)
    ]

    assert lexical.top_paths[0] == "docs/provider-keywords.md"
    assert lexical.hit_at_1 is False
    assert lexical.lexical_only is True

    assert full.top_paths[0] == "docs/model-settings.md"
    assert full.unique_top_paths == full.top_paths
    assert full.hit_at_1 is True
    assert full.score_breakdown.taxonomy > 0
    assert full.score_breakdown.keyphrase > 0
    assert full.score_breakdown.name > 0
    assert full.score_breakdown.graph > 0
    assert full.match_reason.graph_reasons
    full_metrics = {metric.name: metric for metric in full.metrics}
    assert full_metrics["recall_at_k"].value == 1.0
    assert full_metrics["reciprocal_rank"].value == 1.0
    assert full_metrics["ndcg_at_k"].value == 1.0
    assert full_metrics["unique_documents_at_k"].value == 2
    assert full_metrics["unique_document_ratio_at_k"].value == 1.0

    assert embedding.score_breakdown.embedding > 0
    assert embedding.score_breakdown.embedding_model_id == "local-fixture-embedding"
    summaries = {summary.strategy: summary for summary in report.summaries}
    assert summaries[RetrievalEvaluationStrategy.TAXONOMY_GRAPH].mean_recall_at_k == 1.0
    assert summaries[RetrievalEvaluationStrategy.TAXONOMY_GRAPH].mean_ndcg_at_k == 1.0
    assert report.warnings == []


def section_node(
    node_id: str,
    name: str,
    path: str,
    metadata: dict[str, object],
) -> KnowledgeNode:
    return KnowledgeNode(
        id=node_id,
        project_id="project-1",
        kind=KnowledgeNodeKind.DOC_SECTION,
        name=name,
        qualified_name=f"{path}#{name}",
        path=path,
        summary="",
        metadata=metadata,
    )


def chunk_for(node: KnowledgeNode, text: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=f"chunk-{node.id}",
        project_id=node.project_id,
        node_id=node.id,
        path=node.path,
        heading=node.name,
        text=text,
        token_count=len(text.split()),
        metadata={},
    )


def annotation_edge(
    *,
    source_id: str,
    edge_type: KnowledgeAnnotationEdgeType,
    target_type: KnowledgeAnnotationTargetType,
    target_value: str,
) -> KnowledgeAnnotationEdge:
    return KnowledgeAnnotationEdge(
        project_id="project-1",
        source_type=KnowledgeAnnotationSourceType.DOC_SECTION,
        source_id=source_id,
        source_path="docs/model-settings.md",
        edge_type=edge_type,
        target_type=target_type,
        target_value=target_value,
        annotation_run_id="annotation-run-1",
        metadata=KnowledgeAnnotationItemMetadata(),
    )
