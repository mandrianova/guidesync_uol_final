from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from guidesync_agent.schemas import (
    KnowledgeAnnotation,
    KnowledgeAnnotationEdge,
    KnowledgeAnnotationMetadata,
    KnowledgeAnnotationRun,
    KnowledgeAnnotationSourceType,
    KnowledgeConcept,
    KnowledgeConceptKind,
    ProjectTaxonomyBootstrapStatus,
)


class AnnotationInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_type: KnowledgeAnnotationSourceType
    source_id: str
    text: str
    project_id: str | None = None
    repo: str | None = None
    path: str | None = None
    heading: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    source_commit: str | None = None
    content_hash: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class AnnotationBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    annotation_runs: list[KnowledgeAnnotationRun]
    annotations: list[KnowledgeAnnotation]
    concepts: list[KnowledgeConcept]
    annotation_edges: list[KnowledgeAnnotationEdge]
    metadata_by_source_id: dict[str, KnowledgeAnnotationMetadata]
    warnings: list[str]


class PreprocessedText(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_text: str
    headings: list[str]
    paragraphs: list[str]
    sentences: list[str]
    inline_code_terms: list[str]
    code_identifier_terms: list[str]
    link_labels: list[str]
    image_alt_texts: list[str]


class NlpEntity(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    label: str


class NlpAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    tokens: list[str]
    lemmas: list[str]
    noun_chunks: list[str]
    entities: list[NlpEntity]
    sentences: list[str]
    warnings: list[str] = Field(default_factory=list)


class PhraseCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str
    source: str
    score: float


class TaxonomyItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: KnowledgeConceptKind
    canonical: str
    aliases: tuple[str, ...] = ()
    bootstrap_status: ProjectTaxonomyBootstrapStatus | None = None


class TaxonomyMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: KnowledgeConceptKind
    canonical: str
    confidence: float
    source: str
    needs_review: bool = False


class NlpAnalyzer(Protocol):
    method_id: str

    def analyze(self, text: str) -> NlpAnalysis: ...


class SemanticKeyphraseRanker(Protocol):
    method_id: str

    def rank(self, text: str, candidates: Sequence[str]) -> dict[str, float]: ...


class SemanticRankingRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    candidates: tuple[str, ...]
    project_id: str | None = None
    run_id: str | None = None
    workflow_task_id: str | None = None
    source_id: str | None = None
