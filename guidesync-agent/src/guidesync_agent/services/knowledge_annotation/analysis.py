from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from guidesync_agent.schemas import ProjectTaxonomy

from .constants import NLP_METHOD_VERSION
from .extraction import (
    KeyphraseExtractionInput,
    PreparedKeyphraseExtraction,
    complete_keyphrase_extraction,
    extract_names,
    extract_tags,
    prepare_keyphrase_extraction,
)
from .models import (
    AnnotationInput,
    NlpAnalyzer,
    PhraseCandidate,
    SemanticKeyphraseRanker,
    SemanticRankingRequest,
    TaxonomyMatch,
)
from .preprocessing import preprocess_markdown
from .providers import default_nlp_analyzer, default_semantic_ranker
from .taxonomy import (
    TaxonomyMappingInput,
    map_to_taxonomy_with_scores,
    taxonomy_semantic_candidates,
)
from .utils import content_hash, stable_id, unique_strings


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


@dataclass(frozen=True)
class PreparedAnnotationSource:
    source: AnnotationInput
    started_at: datetime
    warnings: list[str]
    content_hash: str
    taxonomy: ProjectTaxonomy
    keyphrases: PreparedKeyphraseExtraction
    names: list[str]


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


def analyze_annotation_sources(
    sources: Sequence[AnnotationInput],
    runtime: AnnotationRuntime,
    *,
    cancellation_check: Callable[[], None] | None = None,
) -> list[SourceAnnotationAnalysis]:
    if cancellation_check is not None:
        cancellation_check()
    prepared_sources = [prepare_annotation_source(source, runtime) for source in sources]
    if cancellation_check is not None:
        cancellation_check()
    keyphrase_scores = rank_semantic_requests(
        runtime.semantic_ranker,
        [
            semantic_ranking_request(
                prepared.source,
                prepared.keyphrases.extraction.preprocessed.analysis_text,
                prepared.keyphrases.semantic_candidates,
            )
            for prepared in prepared_sources
        ],
    )
    keyphrases_by_source = [
        complete_keyphrase_extraction(prepared.keyphrases, scores)
        for prepared, scores in zip(prepared_sources, keyphrase_scores, strict=True)
    ]
    if cancellation_check is not None:
        cancellation_check()
    mappings = [
        TaxonomyMappingInput(
            keyphrases=[candidate.value for candidate in keyphrases],
            names=prepared.names,
            taxonomy=prepared.taxonomy,
            semantic_ranker=runtime.semantic_ranker,
            source_text=prepared.keyphrases.extraction.preprocessed.analysis_text,
        )
        for prepared, keyphrases in zip(
            prepared_sources,
            keyphrases_by_source,
            strict=True,
        )
    ]
    taxonomy_scores = rank_semantic_requests(
        runtime.semantic_ranker,
        [
            semantic_ranking_request(
                prepared.source,
                mapping.source_text,
                taxonomy_semantic_candidates(mapping),
            )
            for prepared, mapping in zip(prepared_sources, mappings, strict=True)
        ],
    )
    if cancellation_check is not None:
        cancellation_check()
    return [
        complete_annotation_source(
            prepared,
            keyphrases,
            map_to_taxonomy_with_scores(mapping, scores),
            runtime,
        )
        for prepared, keyphrases, mapping, scores in zip(
            prepared_sources,
            keyphrases_by_source,
            mappings,
            taxonomy_scores,
            strict=True,
        )
    ]


def prepare_annotation_source(
    source: AnnotationInput,
    runtime: AnnotationRuntime,
) -> PreparedAnnotationSource:
    started_at = datetime.now(UTC)
    preprocessed = preprocess_markdown(source.text)
    analysis = runtime.analyzer.analyze(preprocessed.analysis_text)
    source_taxonomy = runtime.taxonomy.model_copy(update={"version": runtime.version})
    keyphrase_extraction = prepare_keyphrase_extraction(
        KeyphraseExtractionInput(
            source=source,
            preprocessed=preprocessed,
            analysis=analysis,
            taxonomy=source_taxonomy,
            semantic_ranker=runtime.semantic_ranker,
        )
    )
    return PreparedAnnotationSource(
        source=source,
        started_at=started_at,
        warnings=analysis.warnings,
        content_hash=source.content_hash or content_hash(source.text),
        taxonomy=source_taxonomy,
        keyphrases=keyphrase_extraction,
        names=extract_names(source, preprocessed, analysis),
    )


def complete_annotation_source(
    prepared: PreparedAnnotationSource,
    keyphrases: list[PhraseCandidate],
    taxonomy_matches: list[TaxonomyMatch],
    runtime: AnnotationRuntime,
) -> SourceAnnotationAnalysis:
    ranker_warnings = getattr(runtime.semantic_ranker, "warnings", [])
    return SourceAnnotationAnalysis(
        started_at=prepared.started_at,
        warnings=unique_strings(
            [*runtime.warnings, *prepared.warnings, *ranker_warnings]
        ),
        content_hash=prepared.content_hash,
        taxonomy=prepared.taxonomy,
        keyphrases=keyphrases,
        names=prepared.names,
        taxonomy_matches=taxonomy_matches,
        tags=extract_tags(prepared.keyphrases.extraction.analysis, keyphrases),
        run_id=stable_id(
            "annotation-run",
            prepared.source.project_id,
            prepared.source.source_type,
            prepared.source.source_id,
            prepared.content_hash,
            runtime.version,
            runtime.method_id,
        ),
    )


def semantic_ranking_request(
    source: AnnotationInput,
    text: str,
    candidates: Sequence[str],
) -> SemanticRankingRequest:
    return SemanticRankingRequest(
        text=text,
        candidates=tuple(candidates),
        project_id=source.project_id,
        run_id=string_metadata(source.metadata, "run_id"),
        workflow_task_id=string_metadata(source.metadata, "workflow_task_id"),
        source_id=source.source_id,
    )


def rank_semantic_requests(
    semantic_ranker: SemanticKeyphraseRanker,
    requests: Sequence[SemanticRankingRequest],
) -> list[dict[str, float]]:
    results: list[dict[str, float]] = [{} for _ in requests]
    active = [(index, request) for index, request in enumerate(requests) if request.candidates]
    if not active:
        return results
    batch_ranker = getattr(semantic_ranker, "rank_many", None)
    if callable(batch_ranker):
        scores = batch_ranker([request for _, request in active])
        for (index, _), score in zip(active, scores, strict=True):
            results[index] = score
        return results
    for index, request in active:
        set_semantic_ranker_context(semantic_ranker, request)
        results[index] = semantic_ranker.rank(request.text, request.candidates)
    return results


def set_semantic_ranker_context(
    semantic_ranker: SemanticKeyphraseRanker,
    request: SemanticRankingRequest,
) -> None:
    setter = getattr(semantic_ranker, "set_usage_context", None)
    if callable(setter):
        setter(
            project_id=request.project_id,
            run_id=request.run_id,
            workflow_task_id=request.workflow_task_id,
            source_id=request.source_id,
        )


def string_metadata(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None
