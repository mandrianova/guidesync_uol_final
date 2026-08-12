from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from guidesync_agent.schemas import (
    KnowledgeAnnotation,
    KnowledgeAnnotationEdge,
    KnowledgeAnnotationEdgeType,
    KnowledgeAnnotationItemMetadata,
    KnowledgeAnnotationKind,
    KnowledgeAnnotationRun,
    KnowledgeAnnotationRunStatus,
    KnowledgeAnnotationRunSummary,
    KnowledgeAnnotationTargetType,
    KnowledgeConcept,
    KnowledgeConceptKind,
    ProjectTaxonomy,
)

from .analysis import analyze_annotation_sources, build_annotation_runtime
from .models import (
    AnnotationBundle,
    AnnotationInput,
    NlpAnalyzer,
    PhraseCandidate,
    SemanticKeyphraseRanker,
    TaxonomyMatch,
)
from .records import (
    AnnotationEdgeInput,
    AnnotationRecordInput,
    annotation_metadata,
    dedupe_annotation_edges,
    dedupe_annotations,
    make_annotation,
    make_edge,
)
from .taxonomy import (
    aliases_for,
    edge_for_taxonomy_match,
)
from .utils import display_keyphrase, stable_id, unique_strings

ANNOTATION_SOURCE_BATCH_SIZE = 64


def annotate_sources(
    sources: Sequence[AnnotationInput],
    *,
    taxonomy: ProjectTaxonomy | None = None,
    taxonomy_version: str | None = None,
    analyzer: NlpAnalyzer | None = None,
    semantic_ranker: SemanticKeyphraseRanker | None = None,
) -> AnnotationBundle:
    if not sources:
        return AnnotationBundle(
            annotation_runs=[],
            annotations=[],
            concepts=[],
            annotation_edges=[],
            metadata_by_source_id={},
            warnings=[],
        )

    runtime = build_annotation_runtime(
        taxonomy,
        taxonomy_version,
        analyzer,
        semantic_ranker,
    )

    annotation_runs: list[KnowledgeAnnotationRun] = []
    annotations: list[KnowledgeAnnotation] = []
    concepts_by_key: dict[tuple[str | None, str | None, str, str], KnowledgeConcept] = {}
    annotation_edges: list[KnowledgeAnnotationEdge] = []
    metadata_by_source_id = {}

    for batch_start in range(0, len(sources), ANNOTATION_SOURCE_BATCH_SIZE):
        source_batch = sources[batch_start : batch_start + ANNOTATION_SOURCE_BATCH_SIZE]
        source_analyses = analyze_annotation_sources(source_batch, runtime)
        for source, source_analysis in zip(source_batch, source_analyses, strict=True):
            source_annotations, source_edges = build_basic_annotation_records(
                source_analysis.run_id,
                source,
                source_analysis.tags,
                source_analysis.keyphrases,
                source_analysis.names,
            )

            taxonomy_annotations, taxonomy_edges, source_concepts = (
                build_taxonomy_annotation_records(
                    source_analysis.run_id,
                    source,
                    source_analysis.taxonomy_matches,
                    runtime.version,
                    source_analysis.taxonomy,
                )
            )
            source_annotations.extend(taxonomy_annotations)
            source_edges.extend(taxonomy_edges)
            concepts_by_key.update(source_concepts)

            source_annotations = dedupe_annotations(source_annotations)
            source_edges = dedupe_annotation_edges(source_edges)
            run = KnowledgeAnnotationRun(
                id=source_analysis.run_id,
                project_id=source.project_id,
                source_type=source.source_type,
                source_id=source.source_id,
                source_path=source.path,
                taxonomy_version=runtime.version,
                method_id=runtime.method_id,
                content_hash=source_analysis.content_hash,
                source_commit=source.source_commit,
                status=KnowledgeAnnotationRunStatus.COMPLETED,
                warnings=source_analysis.warnings,
                summary=KnowledgeAnnotationRunSummary(
                    tags=len(source_analysis.tags),
                    categories=sum(
                        1
                        for item in source_analysis.taxonomy_matches
                        if item.kind == KnowledgeConceptKind.CATEGORY
                    ),
                    keyphrases=len(source_analysis.keyphrases),
                    entities=len(source_analysis.names),
                    concepts=len(source_analysis.taxonomy_matches),
                    edges=len(source_edges),
                ),
                started_at=source_analysis.started_at,
                completed_at=datetime.now(UTC),
            )
            annotation_runs.append(run)
            annotations.extend(source_annotations)
            annotation_edges.extend(source_edges)
            metadata_by_source_id[source.source_id] = annotation_metadata(
                run,
                source_analysis.tags,
                source_analysis.keyphrases,
                source_analysis.names,
                source_analysis.taxonomy_matches,
                source_analysis.warnings,
            )

    return AnnotationBundle(
        annotation_runs=annotation_runs,
        annotations=annotations,
        concepts=list(concepts_by_key.values()),
        annotation_edges=annotation_edges,
        metadata_by_source_id=metadata_by_source_id,
        warnings=unique_strings(runtime.warnings),
    )


def build_basic_annotation_records(
    run_id: str,
    source: AnnotationInput,
    tags: list[str],
    keyphrases: list[PhraseCandidate],
    names: list[str],
) -> tuple[list[KnowledgeAnnotation], list[KnowledgeAnnotationEdge]]:
    annotations = []
    edges = []
    for tag in tags:
        annotations.append(
            make_annotation(
                run_id,
                source,
                AnnotationRecordInput(
                    kind=KnowledgeAnnotationKind.TAG,
                    value=tag,
                    canonical_value=tag,
                    confidence=0.62,
                    annotation_source="nlp-token",
                ),
            )
        )
        edges.append(
            make_edge(
                run_id,
                source,
                AnnotationEdgeInput(
                    edge_type=KnowledgeAnnotationEdgeType.HAS_TAG,
                    target_type=KnowledgeAnnotationTargetType.TAG,
                    target_value=tag,
                    confidence=0.62,
                ),
            )
        )
    for candidate in keyphrases:
        canonical = display_keyphrase(candidate.value)
        annotations.append(keyphrase_annotation(run_id, source, candidate, canonical))
        edges.append(keyphrase_edge(run_id, source, candidate, canonical))
    for name in names:
        annotations.append(name_annotation(run_id, source, name))
        edges.append(name_edge(run_id, source, name))
    return annotations, edges


def keyphrase_annotation(
    run_id: str,
    source: AnnotationInput,
    candidate: PhraseCandidate,
    canonical: str,
) -> KnowledgeAnnotation:
    return make_annotation(
        run_id,
        source,
        AnnotationRecordInput(
            kind=KnowledgeAnnotationKind.KEYPHRASE,
            value=candidate.value,
            canonical_value=canonical,
            confidence=min(candidate.score, 1.0),
            annotation_source=candidate.source,
        ),
    )


def keyphrase_edge(
    run_id: str,
    source: AnnotationInput,
    candidate: PhraseCandidate,
    canonical: str,
) -> KnowledgeAnnotationEdge:
    return make_edge(
        run_id,
        source,
        AnnotationEdgeInput(
            edge_type=KnowledgeAnnotationEdgeType.HAS_KEYPHRASE,
            target_type=KnowledgeAnnotationTargetType.KEYPHRASE,
            target_value=canonical,
            confidence=min(candidate.score, 1.0),
        ),
    )


def name_annotation(
    run_id: str,
    source: AnnotationInput,
    name: str,
) -> KnowledgeAnnotation:
    return make_annotation(
        run_id,
        source,
        AnnotationRecordInput(
            kind=KnowledgeAnnotationKind.EXTRACTED_NAME,
            value=name,
            canonical_value=name,
            confidence=0.74,
            annotation_source="entity",
        ),
    )


def name_edge(
    run_id: str,
    source: AnnotationInput,
    name: str,
) -> KnowledgeAnnotationEdge:
    return make_edge(
        run_id,
        source,
        AnnotationEdgeInput(
            edge_type=KnowledgeAnnotationEdgeType.MENTIONS_NAME,
            target_type=KnowledgeAnnotationTargetType.EXTRACTED_NAME,
            target_value=name,
            confidence=0.74,
        ),
    )


def build_taxonomy_annotation_records(
    run_id: str,
    source: AnnotationInput,
    matches: list[TaxonomyMatch],
    version: str | None,
    taxonomy: ProjectTaxonomy,
) -> tuple[
    list[KnowledgeAnnotation],
    list[KnowledgeAnnotationEdge],
    dict[tuple[str | None, str | None, str, str], KnowledgeConcept],
]:
    annotations = []
    edges = []
    concepts = {}
    for match in matches:
        annotations.append(taxonomy_annotation(run_id, source, match))
        edges.append(taxonomy_edge(run_id, source, match))
        concept_key = (source.project_id, version, match.kind, match.canonical)
        concepts[concept_key] = KnowledgeConcept(
            id=stable_id("concept", *concept_key),
            project_id=source.project_id,
            taxonomy_version=version,
            kind=match.kind,
            canonical_value=match.canonical,
            aliases=aliases_for(match.canonical, taxonomy),
            metadata=KnowledgeAnnotationItemMetadata(
                needs_taxonomy_review=match.needs_review
            ),
        )
    return annotations, edges, concepts


def taxonomy_annotation(
    run_id: str,
    source: AnnotationInput,
    match: TaxonomyMatch,
) -> KnowledgeAnnotation:
    kind = (
        KnowledgeAnnotationKind.CATEGORY
        if match.kind == KnowledgeConceptKind.CATEGORY
        else KnowledgeAnnotationKind.CONCEPT
    )
    return make_annotation(
        run_id,
        source,
        AnnotationRecordInput(
            kind=kind,
            value=match.canonical,
            canonical_value=match.canonical,
            confidence=match.confidence,
            annotation_source=match.source,
            metadata=KnowledgeAnnotationItemMetadata(
                needs_taxonomy_review=match.needs_review
            ),
        ),
    )


def taxonomy_edge(
    run_id: str,
    source: AnnotationInput,
    match: TaxonomyMatch,
) -> KnowledgeAnnotationEdge:
    edge_type, target_type = edge_for_taxonomy_match(match)
    return make_edge(
        run_id,
        source,
        AnnotationEdgeInput(
            edge_type=edge_type,
            target_type=target_type,
            target_value=match.canonical,
            confidence=match.confidence,
            metadata=KnowledgeAnnotationItemMetadata(
                needs_taxonomy_review=match.needs_review
            ),
        ),
    )
