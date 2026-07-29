from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from .evaluation import (
    BinaryClassificationCounts,
    EvaluationAdjudicationStatus,
    EvaluationMeasurementStatus,
    EvaluationMetric,
)


class DocumentationObligationSeverity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class ChangeImpactClaimKind(StrEnum):
    FACT = "fact"
    IMPACT = "impact"
    LIMITATION = "limitation"
    OBLIGATION = "obligation"


class ChangeImpactClaimSupport(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    NOT_ENOUGH_EVIDENCE = "not_enough_evidence"


class ChangeImpactGoldObligation(BaseModel):
    id: str
    kind: ChangeImpactClaimKind
    statement: str
    severity: DocumentationObligationSeverity
    evidence_refs: list[str] = Field(min_length=1)
    adjudication_status: EvaluationAdjudicationStatus


class ChangeImpactGoldFile(BaseModel):
    path: str
    documentation_relevant: bool
    obligations: list[ChangeImpactGoldObligation] = Field(default_factory=list)


class ChangeImpactGoldCase(BaseModel):
    case_id: str
    gold_version: str
    files: list[ChangeImpactGoldFile]


class ChangeImpactPredictedClaim(BaseModel):
    id: str
    kind: ChangeImpactClaimKind
    statement: str
    severity: DocumentationObligationSeverity
    support: ChangeImpactClaimSupport
    matched_gold_obligation_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ChangeImpactFileAnalysis(BaseModel):
    path: str
    status: EvaluationMeasurementStatus
    predicted_documentation_relevant: bool | None = None
    claims: list[ChangeImpactPredictedClaim] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_analysis_state(self) -> ChangeImpactFileAnalysis:
        if self.status == EvaluationMeasurementStatus.MEASURED:
            if self.predicted_documentation_relevant is None:
                raise ValueError("measured file analyses require a relevance prediction")
        elif self.predicted_documentation_relevant is not None or self.claims:
            raise ValueError("unmeasured file analyses cannot contain predictions")
        return self


class ChangeImpactEvaluationInput(BaseModel):
    gold: ChangeImpactGoldCase
    analyses: list[ChangeImpactFileAnalysis]
    available_evidence_refs: list[str] = Field(default_factory=list)


class ChangeImpactSeverityResult(BaseModel):
    severity: DocumentationObligationSeverity
    counts: BinaryClassificationCounts
    metrics: list[EvaluationMetric] = Field(default_factory=list)


class ChangeImpactEvaluationReport(BaseModel):
    case_id: str
    gold_version: str
    relevance_counts: BinaryClassificationCounts
    metrics: list[EvaluationMetric] = Field(default_factory=list)
    obligation_by_severity: list[ChangeImpactSeverityResult] = Field(default_factory=list)
    unsupported_claim_ids: list[str] = Field(default_factory=list)
    unmatched_claim_ids: list[str] = Field(default_factory=list)
    duplicate_claim_ids: list[str] = Field(default_factory=list)
    missed_critical_obligation_ids: list[str] = Field(default_factory=list)
    unevaluated_gold_obligation_ids: list[str] = Field(default_factory=list)
    invalid_evidence_refs: list[str] = Field(default_factory=list)
    invalid_gold_obligation_refs: list[str] = Field(default_factory=list)
    failed_files: list[str] = Field(default_factory=list)
    unevaluated_files: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)


class DocumentationTargetAction(StrEnum):
    UPDATE = "update"
    CREATE = "create"


class DocumentationTargetGold(BaseModel):
    id: str
    path: str
    action: DocumentationTargetAction
    section: str | None = None


class DocumentationTargetPrediction(BaseModel):
    id: str
    path: str
    action: DocumentationTargetAction
    section: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class DocumentationPlanningEvaluationInput(BaseModel):
    case_id: str
    gold_targets: list[DocumentationTargetGold]
    planned_targets: list[DocumentationTargetPrediction] = Field(default_factory=list)
    executed_targets: list[DocumentationTargetPrediction] = Field(default_factory=list)
    available_evidence_refs: list[str] = Field(default_factory=list)


class DocumentationPlanningEvaluationReport(BaseModel):
    case_id: str
    metrics: list[EvaluationMetric] = Field(default_factory=list)
    missing_target_ids: list[str] = Field(default_factory=list)
    unnecessary_plan_ids: list[str] = Field(default_factory=list)
    wrong_action_plan_ids: list[str] = Field(default_factory=list)
    wrong_section_plan_ids: list[str] = Field(default_factory=list)
    invalid_evidence_refs: list[str] = Field(default_factory=list)
    planned_not_executed_ids: list[str] = Field(default_factory=list)
    unplanned_executed_ids: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)


class GeneratedClaimSupport(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    NOT_ENOUGH_EVIDENCE = "not_enough_evidence"


class GeneratedClaimRelevance(StrEnum):
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"


class GeneratedAtomicClaim(BaseModel):
    id: str
    statement: str
    support: GeneratedClaimSupport
    relevance: GeneratedClaimRelevance
    matched_gold_obligation_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ContentPreservationCheck(BaseModel):
    id: str
    before_hash: str
    after_hash: str


class StructuralValidationCheck(BaseModel):
    id: str
    passed: bool


class DocumentationGenerationEvaluationInput(BaseModel):
    case_id: str
    status: EvaluationMeasurementStatus
    gold_obligations: list[ChangeImpactGoldObligation]
    claims: list[GeneratedAtomicClaim] = Field(default_factory=list)
    available_evidence_refs: list[str] = Field(default_factory=list)
    planned_scope_ids: list[str] = Field(default_factory=list)
    changed_scope_ids: list[str] = Field(default_factory=list)
    preservation_checks: list[ContentPreservationCheck] = Field(default_factory=list)
    structural_checks: list[StructuralValidationCheck] = Field(default_factory=list)
    output_artifact_ref: str | None = None

    @model_validator(mode="after")
    def validate_generation_state(self) -> DocumentationGenerationEvaluationInput:
        if self.status != EvaluationMeasurementStatus.MEASURED and self.claims:
            raise ValueError("unmeasured generation cannot contain scored claims")
        return self


class DocumentationGenerationEvaluationReport(BaseModel):
    case_id: str
    status: EvaluationMeasurementStatus
    metrics: list[EvaluationMetric] = Field(default_factory=list)
    missing_obligation_ids: list[str] = Field(default_factory=list)
    unsupported_claim_ids: list[str] = Field(default_factory=list)
    contradicted_claim_ids: list[str] = Field(default_factory=list)
    irrelevant_claim_ids: list[str] = Field(default_factory=list)
    duplicate_claim_ids: list[str] = Field(default_factory=list)
    invalid_evidence_refs: list[str] = Field(default_factory=list)
    unplanned_changed_scope_ids: list[str] = Field(default_factory=list)
    altered_surrounding_content_ids: list[str] = Field(default_factory=list)
    failed_structural_check_ids: list[str] = Field(default_factory=list)
    output_artifact_ref: str | None = None
    findings: list[str] = Field(default_factory=list)


class ValidationGoldDefect(BaseModel):
    id: str
    severity: DocumentationObligationSeverity
    evidence_refs: list[str] = Field(min_length=1)
    adjudication_status: EvaluationAdjudicationStatus


class ValidationFindingJudgment(BaseModel):
    id: str
    matched_gold_defect_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ValidationEvaluationInput(BaseModel):
    case_id: str
    status: EvaluationMeasurementStatus
    gold_defects: list[ValidationGoldDefect] = Field(default_factory=list)
    findings: list[ValidationFindingJudgment] = Field(default_factory=list)
    corrected_gold_defect_ids: list[str] = Field(default_factory=list)
    residual_gold_defect_ids: list[str] = Field(default_factory=list)
    available_evidence_refs: list[str] = Field(default_factory=list)
    pre_validation_artifact_ref: str | None = None
    post_validation_artifact_ref: str | None = None

    @model_validator(mode="after")
    def validate_validator_state(self) -> ValidationEvaluationInput:
        outputs = (
            self.findings,
            self.corrected_gold_defect_ids,
            self.residual_gold_defect_ids,
        )
        if self.status != EvaluationMeasurementStatus.MEASURED and any(outputs):
            raise ValueError("unmeasured validation cannot contain scored results")
        return self


class ValidationEvaluationReport(BaseModel):
    case_id: str
    status: EvaluationMeasurementStatus
    detection_counts: BinaryClassificationCounts
    metrics: list[EvaluationMetric] = Field(default_factory=list)
    missed_defect_ids: list[str] = Field(default_factory=list)
    false_positive_finding_ids: list[str] = Field(default_factory=list)
    duplicate_finding_ids: list[str] = Field(default_factory=list)
    invalid_evidence_refs: list[str] = Field(default_factory=list)
    invalid_gold_defect_refs: list[str] = Field(default_factory=list)
    pre_validation_artifact_ref: str | None = None
    post_validation_artifact_ref: str | None = None
    findings: list[str] = Field(default_factory=list)


class ReindexGoldDocument(BaseModel):
    path: str
    expected_commit: str
    expected_content_hash: str
    expected_sections: list[str] = Field(default_factory=list)
    expected_query_ids: list[str] = Field(default_factory=list)


class ReindexObservedDocument(BaseModel):
    path: str
    indexed_commit: str | None = None
    indexed_content_hash: str | None = None
    indexed_sections: list[str] = Field(default_factory=list)
    successful_query_ids: list[str] = Field(default_factory=list)


class ReindexEvaluationInput(BaseModel):
    case_id: str
    status: EvaluationMeasurementStatus
    gold_documents: list[ReindexGoldDocument]
    observed_documents: list[ReindexObservedDocument] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_reindex_state(self) -> ReindexEvaluationInput:
        if self.status != EvaluationMeasurementStatus.MEASURED and self.observed_documents:
            raise ValueError("unmeasured reindex cannot contain observed documents")
        return self


class ReindexEvaluationReport(BaseModel):
    case_id: str
    status: EvaluationMeasurementStatus
    metrics: list[EvaluationMetric] = Field(default_factory=list)
    missing_document_paths: list[str] = Field(default_factory=list)
    unexpected_document_paths: list[str] = Field(default_factory=list)
    stale_commit_paths: list[str] = Field(default_factory=list)
    stale_content_paths: list[str] = Field(default_factory=list)
    missing_section_refs: list[str] = Field(default_factory=list)
    failed_query_ids: list[str] = Field(default_factory=list)
