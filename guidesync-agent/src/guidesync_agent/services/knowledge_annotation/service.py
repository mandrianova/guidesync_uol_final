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

from .constants import NLP_METHOD_VERSION
from .extraction import extract_keyphrases, extract_names, extract_tags
from .models import (
    AnnotationBundle,
    AnnotationInput,
    NlpAnalyzer,
    SemanticKeyphraseRanker,
)
from .preprocessing import preprocess_markdown
from .providers import default_nlp_analyzer, default_semantic_ranker
from .records import (
    annotation_metadata,
    dedupe_annotation_edges,
    dedupe_annotations,
    make_annotation,
    make_edge,
)
from .taxonomy import aliases_for, edge_for_taxonomy_match, map_to_taxonomy
from .utils import content_hash, display_keyphrase, stable_id, unique_strings


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

    warnings: list[str] = []
    selected_taxonomy = taxonomy or ProjectTaxonomy(version=taxonomy_version)
    version = taxonomy_version or selected_taxonomy.version
    analyzer = analyzer or default_nlp_analyzer(warnings)
    semantic_ranker = semantic_ranker or default_semantic_ranker(warnings)
    method_id = f"{NLP_METHOD_VERSION}+{analyzer.method_id}+{semantic_ranker.method_id}"

    annotation_runs: list[KnowledgeAnnotationRun] = []
    annotations: list[KnowledgeAnnotation] = []
    concepts_by_key: dict[tuple[str | None, str | None, str, str], KnowledgeConcept] = {}
    annotation_edges: list[KnowledgeAnnotationEdge] = []
    metadata_by_source_id = {}

    for source in sources:
        set_semantic_ranker_context(semantic_ranker, source)
        now = datetime.now(UTC)
        preprocessed = preprocess_markdown(source.text)
        analysis = analyzer.analyze(preprocessed.analysis_text)
        source_warnings = unique_strings([*warnings, *analysis.warnings])
        source_hash = source.content_hash or content_hash(source.text)
        source_taxonomy = selected_taxonomy.model_copy(update={"version": version})
        keyphrases = extract_keyphrases(
            source,
            preprocessed,
            analysis,
            source_taxonomy,
            semantic_ranker,
        )
        names = extract_names(source, preprocessed, analysis)
        taxonomy_matches = map_to_taxonomy(
            [candidate.value for candidate in keyphrases],
            names,
            source_taxonomy,
            semantic_ranker,
            preprocessed.analysis_text,
        )
        tags = extract_tags(analysis, keyphrases)
        run_id = stable_id(
            "annotation-run",
            source.project_id,
            source.source_type,
            source.source_id,
            source_hash,
            version,
            method_id,
        )

        source_annotations: list[KnowledgeAnnotation] = []
        source_edges: list[KnowledgeAnnotationEdge] = []

        for tag in tags:
            source_annotations.append(
                make_annotation(
                    run_id,
                    source,
                    KnowledgeAnnotationKind.TAG,
                    tag,
                    tag,
                    0.62,
                    "nlp-token",
                )
            )
            source_edges.append(
                make_edge(
                    run_id,
                    source,
                    KnowledgeAnnotationEdgeType.HAS_TAG,
                    KnowledgeAnnotationTargetType.TAG,
                    tag,
                    0.62,
                )
            )

        for candidate in keyphrases:
            canonical = display_keyphrase(candidate.value)
            source_annotations.append(
                make_annotation(
                    run_id,
                    source,
                    KnowledgeAnnotationKind.KEYPHRASE,
                    candidate.value,
                    canonical,
                    min(candidate.score, 1.0),
                    candidate.source,
                )
            )
            source_edges.append(
                make_edge(
                    run_id,
                    source,
                    KnowledgeAnnotationEdgeType.HAS_KEYPHRASE,
                    KnowledgeAnnotationTargetType.KEYPHRASE,
                    canonical,
                    min(candidate.score, 1.0),
                )
            )

        for name in names:
            source_annotations.append(
                make_annotation(
                    run_id,
                    source,
                    KnowledgeAnnotationKind.EXTRACTED_NAME,
                    name,
                    name,
                    0.74,
                    "entity",
                )
            )
            source_edges.append(
                make_edge(
                    run_id,
                    source,
                    KnowledgeAnnotationEdgeType.MENTIONS_NAME,
                    KnowledgeAnnotationTargetType.EXTRACTED_NAME,
                    name,
                    0.74,
                )
            )

        for match in taxonomy_matches:
            source_annotations.append(
                make_annotation(
                    run_id,
                    source,
                    KnowledgeAnnotationKind.CATEGORY
                    if match.kind == KnowledgeConceptKind.CATEGORY
                    else KnowledgeAnnotationKind.CONCEPT,
                    match.canonical,
                    match.canonical,
                    match.confidence,
                    match.source,
                    metadata=KnowledgeAnnotationItemMetadata(
                        needs_taxonomy_review=match.needs_review
                    ),
                )
            )
            edge_type, target_type = edge_for_taxonomy_match(match)
            source_edges.append(
                make_edge(
                    run_id,
                    source,
                    edge_type,
                    target_type,
                    match.canonical,
                    match.confidence,
                    metadata=KnowledgeAnnotationItemMetadata(
                        needs_taxonomy_review=match.needs_review
                    ),
                )
            )
            concept_key = (source.project_id, version, match.kind, match.canonical)
            concepts_by_key.setdefault(
                concept_key,
                KnowledgeConcept(
                    id=stable_id("concept", *concept_key),
                    project_id=source.project_id,
                    taxonomy_version=version,
                    kind=match.kind,
                    canonical_value=match.canonical,
                    aliases=aliases_for(match.canonical, source_taxonomy),
                    metadata=KnowledgeAnnotationItemMetadata(
                        needs_taxonomy_review=match.needs_review
                    ),
                ),
            )

        source_annotations = dedupe_annotations(source_annotations)
        source_edges = dedupe_annotation_edges(source_edges)
        run = KnowledgeAnnotationRun(
            id=run_id,
            project_id=source.project_id,
            source_type=source.source_type,
            source_id=source.source_id,
            source_path=source.path,
            taxonomy_version=version,
            method_id=method_id,
            content_hash=source_hash,
            source_commit=source.source_commit,
            status=KnowledgeAnnotationRunStatus.COMPLETED,
            warnings=source_warnings,
            summary=KnowledgeAnnotationRunSummary(
                tags=len(tags),
                categories=sum(
                    1 for item in taxonomy_matches if item.kind == KnowledgeConceptKind.CATEGORY
                ),
                keyphrases=len(keyphrases),
                entities=len(names),
                concepts=len(taxonomy_matches),
                edges=len(source_edges),
            ),
            started_at=now,
            completed_at=datetime.now(UTC),
        )
        annotation_runs.append(run)
        annotations.extend(source_annotations)
        annotation_edges.extend(source_edges)
        metadata_by_source_id[source.source_id] = annotation_metadata(
            run,
            tags,
            keyphrases,
            names,
            taxonomy_matches,
            source_warnings,
        )

    return AnnotationBundle(
        annotation_runs=annotation_runs,
        annotations=annotations,
        concepts=list(concepts_by_key.values()),
        annotation_edges=annotation_edges,
        metadata_by_source_id=metadata_by_source_id,
        warnings=unique_strings(warnings),
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
