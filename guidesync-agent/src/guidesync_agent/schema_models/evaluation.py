from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from .knowledge import KnowledgeSearchMatchedTerms, KnowledgeSearchScoreBreakdown


class RetrievalEvaluationStrategy(StrEnum):
    LEXICAL = "lexical"
    TAXONOMY_GRAPH = "taxonomy_graph"
    LEXICAL_EMBEDDING = "lexical_embedding"


class RetrievalEvaluationCase(BaseModel):
    id: str
    query: str
    expected_top_paths: list[str] = Field(min_length=1)
    taxonomy_version: str | None = None
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    keyphrases: list[str] = Field(default_factory=list)
    extracted_names: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    documentation_areas: list[str] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=50)


class RetrievalEvaluationMatchReason(BaseModel):
    matched_terms: KnowledgeSearchMatchedTerms = Field(default_factory=KnowledgeSearchMatchedTerms)
    graph_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RetrievalEvaluationCaseResult(BaseModel):
    case_id: str
    strategy: RetrievalEvaluationStrategy
    expected_top_paths: list[str]
    top_paths: list[str] = Field(default_factory=list)
    top_score: float = 0.0
    hit_at_1: bool = False
    hit_at_k: bool = False
    lexical_only: bool = False
    score_breakdown: KnowledgeSearchScoreBreakdown = Field(
        default_factory=KnowledgeSearchScoreBreakdown
    )
    match_reason: RetrievalEvaluationMatchReason = Field(
        default_factory=RetrievalEvaluationMatchReason
    )


class RetrievalEvaluationStrategySummary(BaseModel):
    strategy: RetrievalEvaluationStrategy
    cases: int
    hit_at_1: int = 0
    hit_at_k: int = 0
    mean_top_score: float = 0.0
    lexical_only_results: int = 0
    annotation_signal_results: int = 0
    embedding_signal_results: int = 0


class RetrievalEvaluationReport(BaseModel):
    cases: list[RetrievalEvaluationCase]
    results: list[RetrievalEvaluationCaseResult]
    summaries: list[RetrievalEvaluationStrategySummary]
    warnings: list[str] = Field(default_factory=list)
