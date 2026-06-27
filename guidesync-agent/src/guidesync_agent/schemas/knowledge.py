from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_serializer

from .project import ProjectTaxonomy
from .repository import DocumentationInput, RepositoryInput


class KnowledgeIndexStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class KnowledgeNodeKind(StrEnum):
    REPOSITORY = "repository"
    DOC_PAGE = "doc_page"
    DOC_SECTION = "doc_section"


class KnowledgeEdgeType(StrEnum):
    CONTAINS = "contains"


class KnowledgeAnnotationSourceType(StrEnum):
    DOC_PAGE = "doc_page"
    DOC_SECTION = "doc_section"
    LLM_ANALYSIS = "llm_analysis"


class KnowledgeAnnotationRunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    RUNNING = "running"


class KnowledgeAnnotationKind(StrEnum):
    TAG = "tag"
    KEYPHRASE = "keyphrase"
    EXTRACTED_NAME = "extracted_name"
    CATEGORY = "category"
    CONCEPT = "concept"


class KnowledgeConceptKind(StrEnum):
    CATEGORY = "category"
    COMPONENT = "component"
    WORKFLOW = "workflow"
    DOCUMENTATION_AREA = "documentation_area"
    DOMAIN_TERM = "domain_term"
    CANDIDATE = "candidate"


class KnowledgeAnnotationEdgeType(StrEnum):
    HAS_TAG = "HAS_TAG"
    HAS_KEYPHRASE = "HAS_KEYPHRASE"
    MENTIONS_NAME = "MENTIONS_NAME"
    IN_CATEGORY = "IN_CATEGORY"
    DESCRIBES_COMPONENT = "DESCRIBES_COMPONENT"
    COVERS_WORKFLOW = "COVERS_WORKFLOW"
    BELONGS_TO_DOC_AREA = "BELONGS_TO_DOC_AREA"
    MAPS_TO_CONCEPT = "MAPS_TO_CONCEPT"


class KnowledgeAnnotationTargetType(StrEnum):
    TAG = "tag"
    KEYPHRASE = "keyphrase"
    EXTRACTED_NAME = "extracted_name"
    CATEGORY = "category"
    COMPONENT = "component"
    WORKFLOW = "workflow"
    DOCUMENTATION_AREA = "documentation_area"
    CONCEPT = "concept"


class KnowledgeTagCategory(StrEnum):
    TAG = "tag"
    CATEGORY = "category"
    KEYPHRASE = "keyphrase"
    EXTRACTED_NAME = "extracted_name"
    CONCEPT = "concept"


class KnowledgeAnnotationEvidence(BaseModel):
    path: str | None = None
    heading: str | None = None
    source_commit: str | None = None
    line_range: list[int | None] | None = None

    @model_serializer
    def serialize(self) -> dict[str, object]:
        return {
            key: value
            for key, value in {
                "path": self.path,
                "heading": self.heading,
                "source_commit": self.source_commit,
                "line_range": self.line_range,
            }.items()
            if value is not None
        }


class KnowledgeAnnotationItemMetadata(BaseModel):
    needs_taxonomy_review: bool | None = None

    @model_serializer
    def serialize(self) -> dict[str, object]:
        if self.needs_taxonomy_review is None:
            return {}
        return {"needs_taxonomy_review": self.needs_taxonomy_review}


class KnowledgeAnnotationRunSummary(BaseModel):
    tags: int = 0
    categories: int = 0
    keyphrases: int = 0
    entities: int = 0
    concepts: int = 0
    edges: int = 0


class KnowledgeAnnotationMetadata(BaseModel):
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    keyphrases: list[str] = Field(default_factory=list)
    extracted_names: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    annotation_terms: list[str] = Field(default_factory=list)
    annotation_run_id: str
    annotation_method_id: str
    taxonomy_version: str | None = None
    annotation_warnings: list[str] = Field(default_factory=list)
    needs_taxonomy_review: list[str] = Field(default_factory=list)


class KnowledgeIndexRequest(BaseModel):
    project_id: str | None = None
    repositories: list[RepositoryInput] = Field(default_factory=list)
    documentation: list[DocumentationInput] = Field(default_factory=list)
    taxonomy: ProjectTaxonomy | None = None
    taxonomy_version: str | None = None
    max_file_bytes: int = Field(default=200_000, ge=1, le=2_000_000)


class ProjectKnowledgeIndexRequest(BaseModel):
    max_file_bytes: int = Field(default=200_000, ge=1, le=2_000_000)


class KnowledgeIndexSummary(BaseModel):
    repositories: int = 0
    files: int = 0
    documentation_sources: int = 0
    documents: int = 0
    sections: int = 0
    nodes: int = 0
    edges: int = 0
    chunks: int = 0
    annotation_runs: int = 0
    annotations: int = 0
    concepts: int = 0
    annotation_edges: int = 0
    indexed_commit_sha: str | None = None
    previous_indexed_commit_sha: str | None = None
    changed_documentation_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class KnowledgeIndexRun(BaseModel):
    id: str = Field(default_factory=lambda: f"kg-run-{uuid4().hex[:10]}")
    project_id: str | None = None
    status: KnowledgeIndexStatus = KnowledgeIndexStatus.QUEUED
    source_ref: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    request: KnowledgeIndexRequest
    summary: KnowledgeIndexSummary = Field(default_factory=KnowledgeIndexSummary)


class KnowledgeNode(BaseModel):
    id: str
    project_id: str | None = None
    repo: str | None = None
    kind: KnowledgeNodeKind
    name: str
    qualified_name: str
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    summary: str = ""
    content_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeEdge(BaseModel):
    id: str
    project_id: str | None = None
    source_node_id: str
    target_node_id: str
    edge_type: KnowledgeEdgeType
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeChunk(BaseModel):
    id: str
    project_id: str | None = None
    node_id: str
    repo: str | None = None
    path: str | None = None
    heading: str | None = None
    text: str
    token_count: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeAnnotationRun(BaseModel):
    id: str = Field(default_factory=lambda: f"annotation-run-{uuid4().hex[:10]}")
    project_id: str | None = None
    source_type: KnowledgeAnnotationSourceType = KnowledgeAnnotationSourceType.DOC_SECTION
    source_id: str | None = None
    source_path: str | None = None
    taxonomy_version: str | None = None
    method_id: str
    content_hash: str | None = None
    source_commit: str | None = None
    status: KnowledgeAnnotationRunStatus = KnowledgeAnnotationRunStatus.COMPLETED
    warnings: list[str] = Field(default_factory=list)
    summary: KnowledgeAnnotationRunSummary = Field(default_factory=KnowledgeAnnotationRunSummary)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeAnnotation(BaseModel):
    id: str = Field(default_factory=lambda: f"annotation-{uuid4().hex[:10]}")
    run_id: str
    project_id: str | None = None
    source_type: KnowledgeAnnotationSourceType
    source_id: str
    source_path: str | None = None
    kind: KnowledgeAnnotationKind
    value: str
    normalized_value: str
    canonical_value: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str
    evidence: KnowledgeAnnotationEvidence = Field(default_factory=KnowledgeAnnotationEvidence)
    metadata: KnowledgeAnnotationItemMetadata = Field(
        default_factory=KnowledgeAnnotationItemMetadata
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeConcept(BaseModel):
    id: str = Field(default_factory=lambda: f"concept-{uuid4().hex[:10]}")
    project_id: str | None = None
    taxonomy_version: str | None = None
    kind: KnowledgeConceptKind
    canonical_value: str
    aliases: list[str] = Field(default_factory=list)
    metadata: KnowledgeAnnotationItemMetadata = Field(
        default_factory=KnowledgeAnnotationItemMetadata
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeAnnotationEdge(BaseModel):
    id: str = Field(default_factory=lambda: f"annotation-edge-{uuid4().hex[:10]}")
    project_id: str | None = None
    source_type: KnowledgeAnnotationSourceType
    source_id: str
    source_path: str | None = None
    edge_type: KnowledgeAnnotationEdgeType
    target_type: KnowledgeAnnotationTargetType
    target_value: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_ref: str | None = None
    annotation_run_id: str
    metadata: KnowledgeAnnotationItemMetadata = Field(
        default_factory=KnowledgeAnnotationItemMetadata
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeGraphSnapshot(BaseModel):
    run: KnowledgeIndexRun
    nodes: list[KnowledgeNode]
    edges: list[KnowledgeEdge]
    chunks: list[KnowledgeChunk]
    annotation_runs: list[KnowledgeAnnotationRun] = Field(default_factory=list)
    annotations: list[KnowledgeAnnotation] = Field(default_factory=list)
    concepts: list[KnowledgeConcept] = Field(default_factory=list)
    annotation_edges: list[KnowledgeAnnotationEdge] = Field(default_factory=list)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    project_id: str | None = None
    kinds: list[KnowledgeNodeKind] = Field(default_factory=list)
    path_prefixes: list[str] = Field(default_factory=list)
    taxonomy_version: str | None = None
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    keyphrases: list[str] = Field(default_factory=list)
    extracted_names: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    documentation_areas: list[str] = Field(default_factory=list)
    include_diagnostics: bool = True
    limit: int = Field(default=10, ge=1, le=50)


class KnowledgeSearchScoreBreakdown(BaseModel):
    full_text: float = 0.0
    taxonomy: float = 0.0
    keyphrase: float = 0.0
    name: float = 0.0
    graph: float = 0.0
    embedding: float = 0.0
    final: float = 0.0
    embedding_model_id: str | None = None
    lexical_only: bool = False


class KnowledgeSearchMatchedTerms(BaseModel):
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    keyphrases: list[str] = Field(default_factory=list)
    extracted_names: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    documentation_areas: list[str] = Field(default_factory=list)


class KnowledgeSearchGraphReason(BaseModel):
    source_id: str
    edge_type: str
    target_type: str | None = None
    target_value: str | None = None
    evidence_ref: str | None = None
    needs_taxonomy_review: bool = False


class KnowledgeSearchDiagnostics(BaseModel):
    score_breakdown: KnowledgeSearchScoreBreakdown = Field(
        default_factory=KnowledgeSearchScoreBreakdown
    )
    matched_terms: KnowledgeSearchMatchedTerms = Field(default_factory=KnowledgeSearchMatchedTerms)
    graph_reasons: list[KnowledgeSearchGraphReason] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    taxonomy_version: str | None = None
    ranking_strategy: str = "taxonomy-graph-text-v1"


class KnowledgeSearchResult(BaseModel):
    node: KnowledgeNode
    chunk: KnowledgeChunk | None = None
    score: float
    matched_text: str
    diagnostics: KnowledgeSearchDiagnostics = Field(default_factory=KnowledgeSearchDiagnostics)


class KnowledgeDocumentRef(BaseModel):
    id: str
    project_id: str | None = None
    repo: str | None = None
    path: str
    title: str
    summary: str = ""
    content_hash: str | None = None
    source_commit: str | None = None
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    keyphrases: list[str] = Field(default_factory=list)
    extracted_names: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)
    section_count: int = 0


class KnowledgeSectionRef(BaseModel):
    id: str
    project_id: str | None = None
    document_id: str
    repo: str | None = None
    path: str
    heading: str
    start_line: int | None = None
    end_line: int | None = None
    summary: str = ""
    content_hash: str | None = None
    source_commit: str | None = None
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    keyphrases: list[str] = Field(default_factory=list)
    extracted_names: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)


class KnowledgeDocumentRefs(BaseModel):
    documents: list[KnowledgeDocumentRef]
    sections: list[KnowledgeSectionRef]


class KnowledgeTag(BaseModel):
    value: str
    count: int
    category: KnowledgeTagCategory = KnowledgeTagCategory.TAG
