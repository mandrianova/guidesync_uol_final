from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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

from .constants import NLP_METHOD_VERSION
from .extraction import KeyphraseExtractionInput, extract_keyphrases, extract_names, extract_tags
from .models import (
    AnnotationBundle,
    AnnotationInput,
    NlpAnalyzer,
    PhraseCandidate,
    SemanticKeyphraseRanker,
    TaxonomyMatch,
)
from .preprocessing import preprocess_markdown
from .providers import default_nlp_analyzer, default_semantic_ranker
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
    TaxonomyMappingInput,
    aliases_for,
    edge_for_taxonomy_match,
    map_to_taxonomy,
)
from .utils import content_hash, display_keyphrase, stable_id, unique_strings


@dataclass(frozen=True)
class AnnotationRuntime:
    warnings: list[str]
    taxonomy: ProjectTaxonomy
    version: str | None
    analyzer: NlpAnalyzer
    semantic_ranker: SemanticKeyphraseRanker
    method_id: str


@dataclass(frozen=True)
class SourceAnnotationAnalysis:
    started_at: datetime
    warnings: list[str]
    content_hash: str
    taxonomy: ProjectTaxonomy
    keyphrases: list[PhraseCandidate]
    names: list[str]
    taxonomy_matches: list[TaxonomyMatch]
    tags: list[str]
    run_id: str


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

    for source in sources:
        source_analysis = analyze_annotation_source(source, runtime)

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


def build_annotation_runtime(
    taxonomy: ProjectTaxonomy | None,
    taxonomy_version: str | None,
    analyzer: NlpAnalyzer | None,
    semantic_ranker: SemanticKeyphraseRanker | None,
) -> AnnotationRuntime:
    warnings: list[str] = []
    selected_taxonomy = taxonomy or ProjectTaxonomy(version=taxonomy_version)
    version = taxonomy_version or selected_taxonomy.version
    selected_analyzer = analyzer or default_nlp_analyzer(warnings)
    selected_ranker = semantic_ranker or default_semantic_ranker(warnings)
    method_id = (
        f"{NLP_METHOD_VERSION}+{selected_analyzer.method_id}+{selected_ranker.method_id}"
    )
    return AnnotationRuntime(
        warnings,
        selected_taxonomy,
        version,
        selected_analyzer,
        selected_ranker,
        method_id,
    )


def analyze_annotation_source(
    source: AnnotationInput,
    runtime: AnnotationRuntime,
) -> SourceAnnotationAnalysis:
    set_semantic_ranker_context(runtime.semantic_ranker, source)
    started_at = datetime.now(UTC)
    preprocessed = preprocess_markdown(source.text)
    analysis = runtime.analyzer.analyze(preprocessed.analysis_text)
    source_taxonomy = runtime.taxonomy.model_copy(update={"version": runtime.version})
    keyphrases = extract_keyphrases(
        KeyphraseExtractionInput(
            source=source,
            preprocessed=preprocessed,
            analysis=analysis,
            taxonomy=source_taxonomy,
            semantic_ranker=runtime.semantic_ranker,
        )
    )
    names = extract_names(source, preprocessed, analysis)
    taxonomy_matches = map_to_taxonomy(
        TaxonomyMappingInput(
            keyphrases=[candidate.value for candidate in keyphrases],
            names=names,
            taxonomy=source_taxonomy,
            semantic_ranker=runtime.semantic_ranker,
            source_text=preprocessed.analysis_text,
        )
    )
    source_hash = source.content_hash or content_hash(source.text)
    return SourceAnnotationAnalysis(
        started_at=started_at,
        warnings=unique_strings([*runtime.warnings, *analysis.warnings]),
        content_hash=source_hash,
        taxonomy=source_taxonomy,
        keyphrases=keyphrases,
        names=names,
        taxonomy_matches=taxonomy_matches,
        tags=extract_tags(analysis, keyphrases),
        run_id=stable_id(
            "annotation-run",
            source.project_id,
            source.source_type,
            source.source_id,
            source_hash,
            runtime.version,
            runtime.method_id,
        ),
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


def set_semantic_ranker_context(
    semantic_ranker: SemanticKeyphraseRanker,
    source: AnnotationInput,
) -> None:
    setter = getattr(semantic_ranker, "set_usage_context", None)
    if not callable(setter):
        return
    setter(
        project_id=source.project_id,
        run_id=string_metadata(source.metadata, "run_id"),
        workflow_task_id=string_metadata(source.metadata, "workflow_task_id"),
        source_id=source.source_id,
    )


def string_metadata(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None
