from __future__ import annotations

from collections.abc import Iterable

from guidesync_agent.schemas import (
    EvaluationMeasurementStatus,
    EvaluationMetric,
    KnowledgeAnnotationEdge,
    KnowledgeChunk,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeSearchGraphReason,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    RetrievalEvaluationCase,
    RetrievalEvaluationCaseResult,
    RetrievalEvaluationMatchReason,
    RetrievalEvaluationReport,
    RetrievalEvaluationStrategy,
    RetrievalEvaluationStrategySummary,
)
from guidesync_agent.services.evaluation_metrics import (
    ndcg_at_k_metric,
    not_evaluated_metric,
    recall_at_k_metric,
    reciprocal_rank_metric,
    stable_unique,
    unique_document_ratio_at_k_metric,
    unique_documents_at_k_metric,
)
from guidesync_agent.services.knowledge_retrieval import score_knowledge_search

EMBEDDING_METADATA_KEYS = {"embedding_model_id", "embedding_similarity", "embedding_score"}


def evaluate_retrieval(
    *,
    cases: list[RetrievalEvaluationCase],
    nodes: list[KnowledgeNode],
    chunks: list[KnowledgeChunk],
    edges: list[KnowledgeEdge],
    annotation_edges: list[KnowledgeAnnotationEdge],
    include_embedding_ablation: bool = False,
) -> RetrievalEvaluationReport:
    results: list[RetrievalEvaluationCaseResult] = []
    warnings: list[str] = []
    lexical_nodes = strip_metadata(nodes)
    lexical_chunks = strip_chunk_metadata(chunks)
    embedding_nodes = strip_metadata(nodes, keep_keys=EMBEDDING_METADATA_KEYS)
    embedding_chunks = strip_chunk_metadata(chunks, keep_keys=EMBEDDING_METADATA_KEYS)

    for case in cases:
        lexical_results = score_knowledge_search(
            lexical_request(case),
            lexical_nodes,
            lexical_chunks,
            [],
            [],
        )
        full_results = score_knowledge_search(
            taxonomy_graph_request(case),
            nodes,
            chunks,
            edges,
            annotation_edges,
        )
        results.append(case_result(case, RetrievalEvaluationStrategy.LEXICAL, lexical_results))
        full_result = case_result(case, RetrievalEvaluationStrategy.TAXONOMY_GRAPH, full_results)
        results.append(full_result)

        if include_embedding_ablation:
            embedding_results = score_knowledge_search(
                lexical_request(case),
                embedding_nodes,
                embedding_chunks,
                [],
                [],
            )
            results.append(
                case_result(
                    case,
                    RetrievalEvaluationStrategy.LEXICAL_EMBEDDING,
                    embedding_results,
                )
            )
        elif has_embedding_metadata([*nodes, *chunks]):
            warnings.append(
                f"{case.id}: embedding metadata present but embedding ablation was not requested"
            )

        if not full_result.hit_at_k:
            warnings.append(f"{case.id}: taxonomy/graph retrieval missed expected top-k paths")

    return RetrievalEvaluationReport(
        cases=cases,
        results=results,
        summaries=summarize_results(results),
        warnings=warnings,
    )


def lexical_request(case: RetrievalEvaluationCase) -> KnowledgeSearchRequest:
    return KnowledgeSearchRequest(query=case.query, limit=case.limit)


def taxonomy_graph_request(case: RetrievalEvaluationCase) -> KnowledgeSearchRequest:
    return KnowledgeSearchRequest(
        query=case.query,
        taxonomy_version=case.taxonomy_version,
        tags=case.tags,
        categories=case.categories,
        keyphrases=case.keyphrases,
        extracted_names=case.extracted_names,
        concepts=case.concepts,
        components=case.components,
        workflows=case.workflows,
        documentation_areas=case.documentation_areas,
        limit=case.limit,
    )


def case_result(
    case: RetrievalEvaluationCase,
    strategy: RetrievalEvaluationStrategy,
    results: list[KnowledgeSearchResult],
) -> RetrievalEvaluationCaseResult:
    expected = set(case.expected_top_paths)
    top_paths = [result.node.path or result.node.qualified_name for result in results]
    unique_top_paths = stable_unique(top_paths)
    metrics = retrieval_metrics(case, top_paths)
    top = results[0] if results else None
    if top is None:
        return RetrievalEvaluationCaseResult(
            case_id=case.id,
            strategy=strategy,
            expected_top_paths=case.expected_top_paths,
            top_paths=top_paths,
            unique_top_paths=unique_top_paths,
            metrics=metrics,
        )
    diagnostics = top.diagnostics
    return RetrievalEvaluationCaseResult(
        case_id=case.id,
        strategy=strategy,
        expected_top_paths=case.expected_top_paths,
        top_paths=top_paths,
        unique_top_paths=unique_top_paths,
        top_score=top.score,
        hit_at_1=bool(unique_top_paths and unique_top_paths[0] in expected),
        hit_at_k=any(path in expected for path in unique_top_paths[: case.limit]),
        lexical_only=diagnostics.score_breakdown.lexical_only,
        score_breakdown=diagnostics.score_breakdown,
        match_reason=RetrievalEvaluationMatchReason(
            matched_terms=diagnostics.matched_terms,
            graph_reasons=format_graph_reasons(diagnostics.graph_reasons),
            warnings=diagnostics.warnings,
        ),
        metrics=metrics,
    )


def retrieval_metrics(
    case: RetrievalEvaluationCase,
    ranked_paths: list[str],
) -> list[EvaluationMetric]:
    metrics = [
        recall_at_k_metric(
            case.expected_top_paths,
            ranked_paths,
            k=case.limit,
        ),
        reciprocal_rank_metric(case.expected_top_paths, ranked_paths),
        unique_documents_at_k_metric(ranked_paths, k=case.limit),
        unique_document_ratio_at_k_metric(ranked_paths, k=case.limit),
    ]
    if case.relevance_grades:
        metrics.append(
            ndcg_at_k_metric(
                case.relevance_grades,
                ranked_paths,
                k=case.limit,
            )
        )
    else:
        metrics.append(
            not_evaluated_metric(
                "ndcg_at_k",
                "graded relevance judgments were not supplied for this case",
            )
        )
    return metrics


def summarize_results(
    results: list[RetrievalEvaluationCaseResult],
) -> list[RetrievalEvaluationStrategySummary]:
    summaries: list[RetrievalEvaluationStrategySummary] = []
    for strategy in RetrievalEvaluationStrategy:
        strategy_results = [result for result in results if result.strategy == strategy]
        if not strategy_results:
            continue
        summaries.append(
            RetrievalEvaluationStrategySummary(
                strategy=strategy,
                cases=len(strategy_results),
                hit_at_1=sum(result.hit_at_1 for result in strategy_results),
                hit_at_k=sum(result.hit_at_k for result in strategy_results),
                mean_top_score=sum(result.top_score for result in strategy_results)
                / len(strategy_results),
                lexical_only_results=sum(result.lexical_only for result in strategy_results),
                annotation_signal_results=sum(
                    has_annotation_signal(result) for result in strategy_results
                ),
                embedding_signal_results=sum(
                    result.score_breakdown.embedding > 0 for result in strategy_results
                ),
                mean_recall_at_k=mean_result_metric(
                    strategy_results,
                    "recall_at_k",
                ),
                mean_reciprocal_rank=mean_result_metric(
                    strategy_results,
                    "reciprocal_rank",
                ),
                mean_ndcg_at_k=mean_result_metric(
                    strategy_results,
                    "ndcg_at_k",
                ),
                mean_unique_documents_at_k=mean_result_metric(
                    strategy_results,
                    "unique_documents_at_k",
                ),
                mean_unique_document_ratio_at_k=mean_result_metric(
                    strategy_results,
                    "unique_document_ratio_at_k",
                ),
            )
        )
    return summaries


def mean_result_metric(
    results: list[RetrievalEvaluationCaseResult],
    metric_name: str,
) -> float | None:
    values = [
        metric.value
        for result in results
        for metric in result.metrics
        if metric.name == metric_name
        and metric.status == EvaluationMeasurementStatus.MEASURED
        and metric.value is not None
    ]
    if not values:
        return None
    return sum(values) / len(values)


def has_annotation_signal(result: RetrievalEvaluationCaseResult) -> bool:
    breakdown = result.score_breakdown
    return any(
        score > 0
        for score in (
            breakdown.taxonomy,
            breakdown.keyphrase,
            breakdown.name,
            breakdown.graph,
        )
    )


def format_graph_reasons(reasons: list[KnowledgeSearchGraphReason]) -> list[str]:
    return [
        " ".join(
            item
            for item in [
                reason.edge_type,
                reason.target_type or "",
                reason.target_value or "",
            ]
            if item
        )
        for reason in reasons
    ]


def strip_metadata(
    nodes: list[KnowledgeNode],
    *,
    keep_keys: set[str] | None = None,
) -> list[KnowledgeNode]:
    return [
        node.model_copy(update={"metadata": filtered_metadata(node.metadata, keep_keys)})
        for node in nodes
    ]


def strip_chunk_metadata(
    chunks: list[KnowledgeChunk],
    *,
    keep_keys: set[str] | None = None,
) -> list[KnowledgeChunk]:
    return [
        chunk.model_copy(update={"metadata": filtered_metadata(chunk.metadata, keep_keys)})
        for chunk in chunks
    ]


def filtered_metadata(metadata: dict[str, object], keep_keys: set[str] | None) -> dict[str, object]:
    if keep_keys is None:
        return {}
    return {key: value for key, value in metadata.items() if key in keep_keys}


def has_embedding_metadata(items: Iterable[KnowledgeNode | KnowledgeChunk]) -> bool:
    return any(any(key in item.metadata for key in EMBEDDING_METADATA_KEYS) for item in items)
