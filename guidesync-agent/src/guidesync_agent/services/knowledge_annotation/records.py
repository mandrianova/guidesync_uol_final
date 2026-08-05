from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from guidesync_agent.schemas import (
    KnowledgeAnnotation,
    KnowledgeAnnotationEdge,
    KnowledgeAnnotationEdgeType,
    KnowledgeAnnotationEvidence,
    KnowledgeAnnotationItemMetadata,
    KnowledgeAnnotationKind,
    KnowledgeAnnotationMetadata,
    KnowledgeAnnotationRun,
    KnowledgeAnnotationTargetType,
    KnowledgeConceptKind,
)

from .models import AnnotationInput, PhraseCandidate, TaxonomyMatch
from .utils import display_keyphrase, normalize_phrase, stable_id, unique_strings


@dataclass(frozen=True)
class AnnotationRecordInput:
    kind: KnowledgeAnnotationKind
    value: str
    canonical_value: str
    confidence: float
    annotation_source: str
    metadata: KnowledgeAnnotationItemMetadata | None = None


@dataclass(frozen=True)
class AnnotationEdgeInput:
    edge_type: KnowledgeAnnotationEdgeType
    target_type: KnowledgeAnnotationTargetType
    target_value: str
    confidence: float
    metadata: KnowledgeAnnotationItemMetadata | None = None


def make_annotation(
    run_id: str,
    source: AnnotationInput,
    data: AnnotationRecordInput,
) -> KnowledgeAnnotation:
    return KnowledgeAnnotation(
        id=stable_id(
            "annotation",
            run_id,
            source.source_id,
            data.kind,
            data.canonical_value,
        ),
        run_id=run_id,
        project_id=source.project_id,
        source_type=source.source_type,
        source_id=source.source_id,
        source_path=source.path,
        kind=data.kind,
        value=data.value,
        normalized_value=normalize_phrase(data.canonical_value),
        canonical_value=data.canonical_value,
        confidence=data.confidence,
        source=data.annotation_source,
        evidence=evidence_for(source),
        metadata=data.metadata or KnowledgeAnnotationItemMetadata(),
    )


def make_edge(
    run_id: str,
    source: AnnotationInput,
    data: AnnotationEdgeInput,
) -> KnowledgeAnnotationEdge:
    return KnowledgeAnnotationEdge(
        id=stable_id(
            "annotation-edge",
            run_id,
            source.source_id,
            data.edge_type,
            data.target_type,
            data.target_value,
        ),
        project_id=source.project_id,
        source_type=source.source_type,
        source_id=source.source_id,
        source_path=source.path,
        edge_type=data.edge_type,
        target_type=data.target_type,
        target_value=data.target_value,
        confidence=data.confidence,
        evidence_ref=evidence_ref_for(source),
        annotation_run_id=run_id,
        metadata=data.metadata or KnowledgeAnnotationItemMetadata(),
    )


def annotation_metadata(
    run: KnowledgeAnnotationRun,
    tags: Sequence[str],
    keyphrases: Sequence[PhraseCandidate],
    names: Sequence[str],
    taxonomy_matches: Sequence[TaxonomyMatch],
    warnings: Sequence[str],
) -> KnowledgeAnnotationMetadata:
    categories = [
        match.canonical
        for match in taxonomy_matches
        if match.kind == KnowledgeConceptKind.CATEGORY and not match.needs_review
    ]
    concepts = [
        match.canonical for match in taxonomy_matches if match.kind != KnowledgeConceptKind.CATEGORY
    ]
    keyphrase_values = [display_keyphrase(candidate.value) for candidate in keyphrases]
    return KnowledgeAnnotationMetadata(
        tags=unique_strings(tags),
        categories=unique_strings(categories),
        keyphrases=unique_strings(keyphrase_values),
        extracted_names=unique_strings(names),
        concepts=unique_strings(concepts),
        annotation_terms=unique_strings([*tags, *keyphrase_values, *names, *concepts]),
        annotation_run_id=run.id,
        annotation_method_id=run.method_id,
        taxonomy_version=run.taxonomy_version,
        annotation_warnings=unique_strings(warnings),
        needs_taxonomy_review=[match.canonical for match in taxonomy_matches if match.needs_review],
    )


def evidence_for(source: AnnotationInput) -> KnowledgeAnnotationEvidence:
    line_range = None
    if source.start_line is not None or source.end_line is not None:
        line_range = [source.start_line, source.end_line]
    return KnowledgeAnnotationEvidence(
        path=source.path,
        heading=source.heading,
        source_commit=source.source_commit,
        line_range=line_range,
    )


def evidence_ref_for(source: AnnotationInput) -> str | None:
    if source.path is None:
        return None
    if source.start_line is None:
        return source.path
    return f"{source.path}:{source.start_line}"


def dedupe_annotations(annotations: Sequence[KnowledgeAnnotation]) -> list[KnowledgeAnnotation]:
    seen: set[tuple[str, str, str]] = set()
    result: list[KnowledgeAnnotation] = []
    for annotation in annotations:
        key = (annotation.kind, annotation.source_id, annotation.canonical_value.lower())
        if key in seen:
            continue
        result.append(annotation)
        seen.add(key)
    return result


def dedupe_annotation_edges(
    edges: Sequence[KnowledgeAnnotationEdge],
) -> list[KnowledgeAnnotationEdge]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[KnowledgeAnnotationEdge] = []
    for edge in edges:
        key = (edge.source_id, edge.edge_type, edge.target_type, edge.target_value.lower())
        if key in seen:
            continue
        result.append(edge)
        seen.add(key)
    return result
