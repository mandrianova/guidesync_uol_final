from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from guidesync_agent.schemas import (
    KnowledgeAnnotationEdge,
    KnowledgeChunk,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeSearchDiagnostics,
    KnowledgeSearchGraphReason,
    KnowledgeSearchMatchedTerms,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    KnowledgeSearchScoreBreakdown,
)
from guidesync_agent.services.knowledge.retrieval_utils import (
    KEYPHRASE_METADATA_KEYS,
    NAME_METADATA_KEYS,
    REVIEW_METADATA_KEY,
    TAXONOMY_METADATA_KEYS,
    embedding_signal,
    list_metadata,
    metadata_text,
    normalize_phrase,
    normalized_set,
    postgres_full_text_signal,
    score_knowledge_text,
    string_metadata,
    token_overlap,
    trim_excerpt,
    unique_sorted,
)
from guidesync_agent.services.text_normalization import tokenize_text


@dataclass(frozen=True)
class KnowledgeCandidateScoreInput:
    request: KnowledgeSearchRequest
    node: KnowledgeNode
    chunk: KnowledgeChunk | None
    text: str
    metadata: dict[str, object]
    graph_edges: Sequence[KnowledgeEdge]
    annotation_edges: Sequence[KnowledgeAnnotationEdge]


def score_knowledge_search(
    request: KnowledgeSearchRequest,
    nodes: list[KnowledgeNode],
    chunks: list[KnowledgeChunk],
    edges: list[KnowledgeEdge],
    annotation_edges: list[KnowledgeAnnotationEdge],
) -> list[KnowledgeSearchResult]:
    node_by_id = {node.id: node for node in nodes}
    graph_edges_by_node = graph_edges_by_node_id(edges)
    annotation_edges_by_source = annotation_edges_by_source_id(annotation_edges)
    results: list[KnowledgeSearchResult] = []

    for node in nodes:
        if not node_matches_filters(node, request):
            continue
        result = score_candidate(
            KnowledgeCandidateScoreInput(
                request=request,
                node=node,
                chunk=None,
                text=" ".join(
                    item
                    for item in [node.name, node.qualified_name, node.path, node.summary]
                    if item
                ),
                metadata=node.metadata,
                graph_edges=graph_edges_by_node.get(node.id, []),
                annotation_edges=annotation_edges_by_source.get(node.id, []),
            )
        )
        if result is not None:
            results.append(result)

    for chunk in chunks:
        node = node_by_id.get(chunk.node_id)
        if node is None or not node_matches_filters(node, request):
            continue
        metadata = {**node.metadata, **chunk.metadata}
        result = score_candidate(
            KnowledgeCandidateScoreInput(
                request=request,
                node=node,
                chunk=chunk,
                text=" ".join(
                    item for item in [chunk.heading, chunk.path, chunk.text] if item
                ),
                metadata=metadata,
                graph_edges=graph_edges_by_node.get(node.id, []),
                annotation_edges=annotation_edges_by_source.get(node.id, []),
            )
        )
        if result is not None:
            results.append(result)

    return dedupe_results_by_node(
        sorted(
            results,
            key=lambda result: (
                result.score,
                result.diagnostics.score_breakdown.taxonomy,
                result.diagnostics.score_breakdown.graph,
                result.chunk is not None,
                result.node.path or "",
                result.node.name,
            ),
            reverse=True,
        ),
        limit=request.limit,
    )


def dedupe_results_by_node(
    results: list[KnowledgeSearchResult],
    *,
    limit: int,
) -> list[KnowledgeSearchResult]:
    selected: list[KnowledgeSearchResult] = []
    seen_node_ids: set[str] = set()
    for result in results:
        if result.node.id in seen_node_ids:
            continue
        seen_node_ids.add(result.node.id)
        selected.append(result)
        if len(selected) >= limit:
            break
    return selected


def score_candidate(data: KnowledgeCandidateScoreInput) -> KnowledgeSearchResult | None:
    request = data.request
    node = data.node
    chunk = data.chunk
    text = data.text
    metadata = data.metadata
    query_tokens = set(tokenize_text(request.query))
    review_terms = normalized_set(list_metadata(metadata, REVIEW_METADATA_KEY))
    text_score = score_knowledge_text(
        request.query,
        f"{text} {metadata_text(metadata)}",
    ) + postgres_full_text_signal(metadata)
    taxonomy_score, taxonomy_matches = score_taxonomy(metadata, request, query_tokens, review_terms)
    keyphrase_score, keyphrase_matches = score_metadata_group(
        metadata,
        request_terms=[*request.tags, *request.keyphrases],
        query_tokens=query_tokens,
        keys=KEYPHRASE_METADATA_KEYS,
        excluded_terms=set(),
        exact_weight=2.2,
        overlap_weight=1.0,
    )
    name_score, name_matches = score_metadata_group(
        metadata,
        request_terms=[*request.extracted_names, *request.components],
        query_tokens=query_tokens,
        keys=NAME_METADATA_KEYS,
        excluded_terms=set(),
        exact_weight=2.4,
        overlap_weight=1.2,
    )
    graph_score, graph_reasons, graph_matches = score_graph(
        data.annotation_edges,
        data.graph_edges,
        request,
        query_tokens,
        review_terms,
    )
    embedding_score, embedding_model_id = embedding_signal(metadata)
    final_score = (
        text_score
        + taxonomy_score * 3.0
        + keyphrase_score * 2.0
        + name_score * 2.0
        + graph_score * 2.5
        + embedding_score
    )
    if final_score <= 0:
        return None

    matched_terms = KnowledgeSearchMatchedTerms(
        tags=unique_sorted(keyphrase_matches.get("tags", [])),
        categories=unique_sorted(taxonomy_matches.get("categories", [])),
        keyphrases=unique_sorted(keyphrase_matches.get("keyphrases", [])),
        extracted_names=unique_sorted(name_matches.get("extracted_names", [])),
        concepts=unique_sorted(taxonomy_matches.get("concepts", [])),
        components=unique_sorted(graph_matches.get("components", [])),
        workflows=unique_sorted(graph_matches.get("workflows", [])),
        documentation_areas=unique_sorted(graph_matches.get("documentation_areas", [])),
    )
    lexical_only = all(
        score == 0
        for score in (taxonomy_score, keyphrase_score, name_score, graph_score, embedding_score)
    )
    warnings = diagnostics_warnings(
        request,
        metadata,
        lexical_only,
        candidate_review_matched=candidate_review_matched(
            request,
            metadata,
            review_terms,
            graph_reasons,
        ),
    )
    diagnostics = KnowledgeSearchDiagnostics(
        score_breakdown=KnowledgeSearchScoreBreakdown(
            full_text=text_score,
            taxonomy=taxonomy_score,
            keyphrase=keyphrase_score,
            name=name_score,
            graph=graph_score,
            embedding=embedding_score,
            final=final_score,
            embedding_model_id=embedding_model_id,
            lexical_only=lexical_only,
        ),
        matched_terms=matched_terms,
        graph_reasons=graph_reasons[:6],
        warnings=warnings,
        taxonomy_version=string_metadata(metadata, "taxonomy_version"),
    )
    return KnowledgeSearchResult(
        node=node,
        chunk=chunk,
        score=final_score,
        matched_text=matched_text(text, request.query, diagnostics),
        diagnostics=diagnostics if request.include_diagnostics else KnowledgeSearchDiagnostics(),
    )


def score_taxonomy(
    metadata: dict[str, object],
    request: KnowledgeSearchRequest,
    query_tokens: set[str],
    review_terms: set[str],
) -> tuple[float, dict[str, list[str]]]:
    requested_terms = [
        *request.categories,
        *request.concepts,
        *request.components,
        *request.workflows,
        *request.documentation_areas,
    ]
    score, matches = score_metadata_group(
        metadata,
        request_terms=requested_terms,
        query_tokens=query_tokens,
        keys=TAXONOMY_METADATA_KEYS,
        excluded_terms=review_terms,
        exact_weight=2.8,
        overlap_weight=1.2,
    )
    return score, matches


def score_metadata_group(  # noqa: PLR0913 - explicit scoring rule inputs
    metadata: dict[str, object],
    *,
    request_terms: Sequence[str],
    query_tokens: set[str],
    keys: Sequence[str],
    excluded_terms: set[str],
    exact_weight: float,
    overlap_weight: float,
) -> tuple[float, dict[str, list[str]]]:
    requested = normalized_set(request_terms)
    score = 0.0
    matches: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        for value in list_metadata(metadata, key):
            normalized = normalize_phrase(value)
            if not normalized or normalized in excluded_terms:
                continue
            value_tokens = set(normalized.split())
            if normalized in requested:
                score += exact_weight
                matches[key].append(value)
                continue
            overlap = token_overlap(query_tokens, value_tokens)
            if overlap >= 0.5:
                score += overlap * overlap_weight
                matches[key].append(value)
    return score, dict(matches)


def score_graph(
    annotation_edges: Sequence[KnowledgeAnnotationEdge],
    graph_edges: Sequence[KnowledgeEdge],
    request: KnowledgeSearchRequest,
    query_tokens: set[str],
    review_terms: set[str],
) -> tuple[float, list[KnowledgeSearchGraphReason], dict[str, list[str]]]:
    requested = normalized_set(
        [
            *request.categories,
            *request.concepts,
            *request.components,
            *request.workflows,
            *request.documentation_areas,
            *request.extracted_names,
        ]
    )
    score = 0.0
    reasons: list[KnowledgeSearchGraphReason] = []
    matches: dict[str, list[str]] = defaultdict(list)

    for edge in annotation_edges:
        normalized = normalize_phrase(edge.target_value)
        needs_review = edge.metadata.needs_taxonomy_review is True or normalized in review_terms
        target_tokens = set(normalized.split())
        exact_match = normalized in requested
        overlap = token_overlap(query_tokens, target_tokens)
        if needs_review and exact_match:
            score += 0.2
        elif exact_match:
            score += 2.0
        elif not needs_review and overlap >= 0.5:
            score += overlap
        else:
            continue
        reasons.append(
            KnowledgeSearchGraphReason(
                source_id=edge.source_id,
                edge_type=edge.edge_type.value,
                target_type=edge.target_type.value,
                target_value=edge.target_value,
                evidence_ref=edge.evidence_ref,
                needs_taxonomy_review=needs_review,
            )
        )
        bucket = graph_match_bucket(edge.target_type.value)
        if bucket is not None:
            matches[bucket].append(edge.target_value)

    if reasons and graph_edges:
        for edge in graph_edges[:3]:
            score += min(edge.confidence, 1.0) * 0.15
            reasons.append(
                KnowledgeSearchGraphReason(
                    source_id=edge.source_node_id,
                    edge_type=edge.edge_type.value,
                    target_value=edge.target_node_id,
                    evidence_ref=edge.evidence_ref,
                )
            )
    return score, reasons, dict(matches)


def graph_match_bucket(target_type: str) -> str | None:
    if target_type == "component":
        return "components"
    if target_type == "workflow":
        return "workflows"
    if target_type == "documentation_area":
        return "documentation_areas"
    return None


def graph_edges_by_node_id(edges: Sequence[KnowledgeEdge]) -> dict[str, list[KnowledgeEdge]]:
    grouped: dict[str, list[KnowledgeEdge]] = defaultdict(list)
    for edge in edges:
        grouped[edge.source_node_id].append(edge)
        grouped[edge.target_node_id].append(edge)
    return dict(grouped)


def annotation_edges_by_source_id(
    edges: Sequence[KnowledgeAnnotationEdge],
) -> dict[str, list[KnowledgeAnnotationEdge]]:
    grouped: dict[str, list[KnowledgeAnnotationEdge]] = defaultdict(list)
    for edge in edges:
        grouped[edge.source_id].append(edge)
    return dict(grouped)


def node_matches_filters(node: KnowledgeNode, request: KnowledgeSearchRequest) -> bool:
    if request.project_id is not None and node.project_id != request.project_id:
        return False
    if request.kinds and node.kind not in request.kinds:
        return False
    if request.path_prefixes:
        path = node.path or ""
        return any(path.startswith(prefix) for prefix in request.path_prefixes)
    return True


def matched_text(text: str, query: str, diagnostics: KnowledgeSearchDiagnostics) -> str:
    if diagnostics.score_breakdown.full_text > 0:
        return trim_excerpt(text, query)
    terms = [
        *diagnostics.matched_terms.categories,
        *diagnostics.matched_terms.concepts,
        *diagnostics.matched_terms.keyphrases,
        *diagnostics.matched_terms.extracted_names,
        *diagnostics.matched_terms.components,
        *diagnostics.matched_terms.workflows,
        *diagnostics.matched_terms.documentation_areas,
    ]
    if terms:
        return f"Matched annotation signals: {', '.join(unique_sorted(terms)[:8])}"
    if diagnostics.graph_reasons:
        reason = diagnostics.graph_reasons[0]
        return f"Matched graph edge: {reason.edge_type} {reason.target_value or ''}".strip()
    return trim_excerpt(text, query)


def diagnostics_warnings(
    request: KnowledgeSearchRequest,
    metadata: dict[str, object],
    lexical_only: bool,
    *,
    candidate_review_matched: bool,
) -> list[str]:
    warnings: list[str] = []
    if lexical_only:
        warnings.append(
            "lexical fallback only; no taxonomy, annotation, graph, or embedding signal"
        )
    metadata_taxonomy = string_metadata(metadata, "taxonomy_version")
    if (
        request.taxonomy_version
        and metadata_taxonomy
        and request.taxonomy_version != metadata_taxonomy
    ):
        warnings.append(
            "taxonomy version mismatch: "
            f"requested {request.taxonomy_version}, indexed {metadata_taxonomy}"
        )
    if candidate_review_matched:
        warnings.append(
            "candidate taxonomy terms require review and were not ranked as controlled categories"
        )
    return warnings


def candidate_review_matched(
    request: KnowledgeSearchRequest,
    metadata: dict[str, object],
    review_terms: set[str],
    graph_reasons: list[KnowledgeSearchGraphReason],
) -> bool:
    requested = normalized_set(
        [
            *request.categories,
            *request.concepts,
            *request.components,
            *request.workflows,
            *request.documentation_areas,
            *request.extracted_names,
        ]
    )
    metadata_categories = normalized_set(list_metadata(metadata, "categories"))
    metadata_concepts = normalized_set(list_metadata(metadata, "concepts"))
    requested_candidate_concepts = requested & metadata_concepts - metadata_categories
    return (
        bool(requested & review_terms)
        or bool(requested_candidate_concepts)
        or requested_terms_overlap_review_terms(requested, review_terms)
        or any(reason.needs_taxonomy_review for reason in graph_reasons)
    )


def requested_terms_overlap_review_terms(requested: set[str], review_terms: set[str]) -> bool:
    return any(
        token_overlap(set(requested_term.split()), set(review_term.split())) >= 0.5
        for requested_term in requested
        for review_term in review_terms
    )
