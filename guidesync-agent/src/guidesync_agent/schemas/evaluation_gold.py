from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from .documentation_evaluation import (
    ChangeImpactGoldCase,
    DocumentationObligationSeverity,
    DocumentationTargetGold,
)
from .evaluation import EvaluationAdjudicationStatus
from .profile_knowledge_evaluation import (
    AnnotationEvaluationSample,
    ProjectProfileEvaluationGold,
    RetrievalEvaluationCase,
)


class KnowledgeCorpusGoldExclusion(BaseModel):
    path: str
    reason: str


class KnowledgeCorpusGold(BaseModel):
    documentation_roots: list[str] = Field(min_length=1)
    supported_extensions: list[str] = Field(min_length=1)
    max_file_bytes: int = Field(ge=1)
    expected_discovered: int = Field(ge=0)
    expected_supported: int = Field(ge=0)
    expected_eligible: int = Field(ge=0)
    expected_indexed: int = Field(ge=0)
    indexed_commit: str
    supported_path_list_sha256: str
    exclusions: list[KnowledgeCorpusGoldExclusion] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts(self) -> KnowledgeCorpusGold:
        if self.expected_eligible > self.expected_discovered:
            raise ValueError("eligible corpus count cannot exceed discovered count")
        if self.expected_supported > self.expected_discovered:
            raise ValueError("supported corpus count cannot exceed discovered count")
        if self.expected_indexed > self.expected_eligible:
            raise ValueError("indexed corpus count cannot exceed eligible count")
        return self


class ValidationDefectTypeGold(BaseModel):
    id: str
    label: str
    severity: DocumentationObligationSeverity
    detection_rule: str


class ReindexQueryGold(BaseModel):
    id: str
    query: str
    expected_path: str


class OptionalDiagnosticGold(BaseModel):
    id: str
    statement: str
    evidence_refs: list[str] = Field(min_length=1)
    exclusion_reason: str


class EvaluationGoldBundle(BaseModel):
    case_id: str
    version: str
    adjudication_status: EvaluationAdjudicationStatus
    project_profile: ProjectProfileEvaluationGold
    knowledge_corpus: KnowledgeCorpusGold
    annotation_samples: list[AnnotationEvaluationSample] = Field(default_factory=list)
    retrieval_cases: list[RetrievalEvaluationCase] = Field(default_factory=list)
    change_impact: ChangeImpactGoldCase
    documentation_targets: list[DocumentationTargetGold] = Field(default_factory=list)
    validation_defect_types: list[ValidationDefectTypeGold] = Field(default_factory=list)
    reindex_queries: list[ReindexQueryGold] = Field(default_factory=list)
    optional_diagnostics: list[OptionalDiagnosticGold] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_bundle(self) -> EvaluationGoldBundle:
        if self.project_profile.version != self.version:
            raise ValueError("project-profile gold version must match the bundle")
        if self.project_profile.adjudication_status != self.adjudication_status:
            raise ValueError("project-profile adjudication status must match the bundle")
        if self.change_impact.case_id != self.case_id:
            raise ValueError("change-impact case id must match the bundle")
        if self.change_impact.gold_version != self.version:
            raise ValueError("change-impact gold version must match the bundle")
        annotation_statuses = {
            sample.adjudication_status for sample in self.annotation_samples
        }
        if annotation_statuses.difference({self.adjudication_status}):
            raise ValueError("annotation adjudication status must match the bundle")
        if any(not sample.source_ref for sample in self.annotation_samples):
            raise ValueError("gold annotation samples require source_ref")
        obligation_statuses = {
            obligation.adjudication_status
            for file in self.change_impact.files
            for obligation in file.obligations
        }
        if obligation_statuses.difference({self.adjudication_status}):
            raise ValueError("obligation adjudication status must match the bundle")

        ensure_unique(
            [sample.id for sample in self.annotation_samples],
            "annotation sample id",
        )
        ensure_unique([case.id for case in self.retrieval_cases], "retrieval case id")
        ensure_unique(
            [
                obligation.id
                for file in self.change_impact.files
                for obligation in file.obligations
            ],
            "gold obligation id",
        )
        ensure_unique(
            [target.id for target in self.documentation_targets],
            "documentation target id",
        )
        ensure_unique(
            [defect.id for defect in self.validation_defect_types],
            "validation defect type id",
        )
        ensure_unique([query.id for query in self.reindex_queries], "reindex query id")
        ensure_unique(
            [diagnostic.id for diagnostic in self.optional_diagnostics],
            "optional diagnostic id",
        )
        return self


def ensure_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label}s must be unique")
