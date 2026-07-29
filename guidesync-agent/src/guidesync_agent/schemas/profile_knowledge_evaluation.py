from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from .evaluation import (
    BinaryClassificationCounts,
    EvaluationAdjudicationStatus,
    EvaluationMetric,
)
from .knowledge import (
    KnowledgeAnnotationEdge,
    KnowledgeChunk,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeSearchMatchedTerms,
    KnowledgeSearchScoreBreakdown,
)


class ProfileClaimLabel(StrEnum):
    SUPPORTED_RELEVANT = "supported_relevant"
    CONTRADICTED = "contradicted"
    NOT_ENOUGH_EVIDENCE = "not_enough_evidence"
    IRRELEVANT = "irrelevant"


class ProfileEvidenceAccess(StrEnum):
    READ = "read"
    SEARCHED = "searched"
    LISTED = "listed"


class ProfileGoldFact(BaseModel):
    id: str
    statement: str
    evidence_refs: list[str] = Field(min_length=1)
    critical: bool = False


class ProfileGoldLabel(BaseModel):
    id: str
    value: str
    aliases: list[str] = Field(default_factory=list)
    parent_id: str | None = None


class ProjectProfileEvaluationGold(BaseModel):
    version: str
    adjudication_status: EvaluationAdjudicationStatus
    facts: list[ProfileGoldFact] = Field(default_factory=list)
    categories: list[ProfileGoldLabel] = Field(default_factory=list)
    concepts: list[ProfileGoldLabel] = Field(default_factory=list)
    critical_repository_paths: list[str] = Field(default_factory=list)


class ProfileEvidenceUse(BaseModel):
    path: str
    access: ProfileEvidenceAccess


class ProfileClaimJudgment(BaseModel):
    id: str
    claim: str
    label: ProfileClaimLabel
    matched_gold_fact_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ProjectProfileEvaluationInput(BaseModel):
    profile_id: str
    claims: list[ProfileClaimJudgment] = Field(default_factory=list)
    predicted_categories: list[str] = Field(default_factory=list)
    predicted_concepts: list[str] = Field(default_factory=list)
    evidence_uses: list[ProfileEvidenceUse] = Field(default_factory=list)
    available_repository_paths: list[str] = Field(default_factory=list)
    comparison_categories: list[str] | None = None
    comparison_concepts: list[str] | None = None


class ProjectProfileEvaluationReport(BaseModel):
    profile_id: str
    gold_version: str
    adjudication_status: EvaluationAdjudicationStatus
    metrics: list[EvaluationMetric] = Field(default_factory=list)
    unsupported_claim_ids: list[str] = Field(default_factory=list)
    missing_gold_fact_ids: list[str] = Field(default_factory=list)
    missing_critical_paths: list[str] = Field(default_factory=list)
    invalid_evidence_refs: list[str] = Field(default_factory=list)
    listed_only_evidence_refs: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)


class CorpusExclusionReason(StrEnum):
    OUTSIDE_ROOT = "outside_root"
    IGNORED_PATH = "ignored_path"
    SYMLINK = "symlink"
    NOT_REGULAR_FILE = "not_regular_file"
    MAX_FILE_BYTES = "max_file_bytes"
    UNSUPPORTED_EXTENSION = "unsupported_extension"
    ELIGIBLE_NOT_INDEXED = "eligible_not_indexed"


class KnowledgeCorpusEntry(BaseModel):
    path: str
    size_bytes: int = Field(ge=0)
    supported: bool
    eligible: bool
    indexed: bool
    exclusion_reason: CorpusExclusionReason | None = None

    @model_validator(mode="after")
    def validate_state(self) -> KnowledgeCorpusEntry:
        if self.indexed:
            if not self.eligible:
                raise ValueError("indexed corpus entries must be eligible")
            if self.exclusion_reason is not None:
                raise ValueError("indexed corpus entries cannot have an exclusion reason")
        elif self.eligible:
            if self.exclusion_reason != CorpusExclusionReason.ELIGIBLE_NOT_INDEXED:
                raise ValueError(
                    "eligible non-indexed entries require eligible_not_indexed"
                )
        elif self.exclusion_reason in {
            None,
            CorpusExclusionReason.ELIGIBLE_NOT_INDEXED,
        }:
            raise ValueError("ineligible corpus entries require an eligibility exclusion")
        return self


class KnowledgeCorpusCounts(BaseModel):
    discovered: int = Field(default=0, ge=0)
    supported: int = Field(default=0, ge=0)
    eligible: int = Field(default=0, ge=0)
    indexed: int = Field(default=0, ge=0)
    excluded: int = Field(default=0, ge=0)
    eligible_not_indexed: int = Field(default=0, ge=0)


class KnowledgeCorpusManifest(BaseModel):
    repository_root: str
    documentation_roots: list[str]
    max_file_bytes: int = Field(ge=1)
    indexed_commit: str | None = None
    entries: list[KnowledgeCorpusEntry] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class KnowledgeCorpusEvaluationReport(BaseModel):
    counts: KnowledgeCorpusCounts
    metrics: list[EvaluationMetric] = Field(default_factory=list)
    excluded_entries: list[KnowledgeCorpusEntry] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)


class AnnotationEvaluationKind(StrEnum):
    TAG = "tag"
    KEYPHRASE = "keyphrase"
    EXTRACTED_NAME = "extracted_name"
    CATEGORY = "category"
    CONCEPT = "concept"
    COMPONENT = "component"
    WORKFLOW = "workflow"
    DOCUMENTATION_AREA = "documentation_area"


class AnnotationEvaluationSample(BaseModel):
    id: str
    kind: AnnotationEvaluationKind
    source_ref: str | None = None
    gold_values: list[str] = Field(default_factory=list)
    predicted_values: list[str] = Field(default_factory=list)
    adjudication_status: EvaluationAdjudicationStatus


class AnnotationEvaluationKindResult(BaseModel):
    kind: AnnotationEvaluationKind
    counts: BinaryClassificationCounts
    metrics: list[EvaluationMetric] = Field(default_factory=list)


class AnnotationEvaluationReport(BaseModel):
    samples: list[AnnotationEvaluationSample] = Field(default_factory=list)
    kind_results: list[AnnotationEvaluationKindResult] = Field(default_factory=list)
    micro_metrics: list[EvaluationMetric] = Field(default_factory=list)
    macro_metrics: list[EvaluationMetric] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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
    relevance_grades: dict[str, float] = Field(default_factory=dict)
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
    unique_top_paths: list[str] = Field(default_factory=list)
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
    metrics: list[EvaluationMetric] = Field(default_factory=list)


class RetrievalEvaluationStrategySummary(BaseModel):
    strategy: RetrievalEvaluationStrategy
    cases: int
    hit_at_1: int = 0
    hit_at_k: int = 0
    mean_top_score: float = 0.0
    lexical_only_results: int = 0
    annotation_signal_results: int = 0
    embedding_signal_results: int = 0
    mean_recall_at_k: float | None = None
    mean_reciprocal_rank: float | None = None
    mean_ndcg_at_k: float | None = None
    mean_unique_documents_at_k: float | None = None
    mean_unique_document_ratio_at_k: float | None = None


class RetrievalEvaluationReport(BaseModel):
    cases: list[RetrievalEvaluationCase]
    results: list[RetrievalEvaluationCaseResult]
    summaries: list[RetrievalEvaluationStrategySummary]
    warnings: list[str] = Field(default_factory=list)


class RetrievalEvaluationSnapshot(BaseModel):
    project_id: str | None = None
    nodes: list[KnowledgeNode]
    chunks: list[KnowledgeChunk]
    edges: list[KnowledgeEdge]
    annotation_edges: list[KnowledgeAnnotationEdge]
