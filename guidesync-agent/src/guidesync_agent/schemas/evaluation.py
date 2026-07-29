from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class PipelineStage(StrEnum):
    INPUT_FREEZE = "input_freeze"
    PROJECT_PROFILE = "project_profile"
    KNOWLEDGE_INDEX = "knowledge_index"
    NLP_ANNOTATION = "nlp_annotation"
    RETRIEVAL = "retrieval"
    CHANGE_ANALYSIS = "change_analysis"
    EDIT_PLANNING = "edit_planning"
    DOCUMENTATION_GENERATION = "documentation_generation"
    VALIDATION = "validation"
    POST_EDIT_REINDEX = "post_edit_reindex"
    END_TO_END = "end_to_end"


class EvaluationConditionKind(StrEnum):
    FULL = "full"
    BASELINE = "baseline"
    ABLATION = "ablation"
    HUMAN_REFERENCE = "human_reference"


class EvaluationMeasurementStatus(StrEnum):
    MEASURED = "measured"
    NOT_EVALUATED = "not_evaluated"
    UNDEFINED = "undefined"
    FAILED = "failed"


class EvaluationAdjudicationStatus(StrEnum):
    DRAFT = "draft"
    SINGLE_ANNOTATOR = "single_annotator"
    ADJUDICATED = "adjudicated"


class EvaluationCondition(BaseModel):
    id: str
    kind: EvaluationConditionKind
    label: str
    removed_stage: PipelineStage | None = None
    replacement: str | None = None
    config_checksum: str | None = None

    @model_validator(mode="after")
    def validate_ablation(self) -> EvaluationCondition:
        if self.kind == EvaluationConditionKind.ABLATION:
            if self.removed_stage is None:
                raise ValueError("ablation conditions require removed_stage")
            if not self.replacement or not self.replacement.strip():
                raise ValueError("ablation conditions require replacement")
        elif self.removed_stage is not None or self.replacement is not None:
            raise ValueError("removed_stage and replacement are only valid for ablations")
        return self


class EvaluationMetric(BaseModel):
    name: str
    status: EvaluationMeasurementStatus
    numerator: float | None = Field(default=None, ge=0.0)
    denominator: float | None = Field(default=None, ge=0.0)
    value: float | None = None
    unit: str = "ratio"
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_measurement(self) -> EvaluationMetric:
        if self.status == EvaluationMeasurementStatus.MEASURED:
            if self.numerator is None or self.denominator is None or self.value is None:
                raise ValueError("measured metrics require numerator, denominator, and value")
            if self.denominator <= 0:
                raise ValueError("measured metrics require a positive denominator")
        elif self.value is not None:
            raise ValueError("unmeasured metrics cannot have a value")
        return self


class BinaryClassificationCounts(BaseModel):
    true_positive: int = Field(default=0, ge=0)
    false_positive: int = Field(default=0, ge=0)
    false_negative: int = Field(default=0, ge=0)
    true_negative: int = Field(default=0, ge=0)


class StageEvaluationResult(BaseModel):
    id: str = Field(default_factory=lambda: f"stage-result-{uuid4().hex[:10]}")
    case_id: str
    condition_id: str
    stage: PipelineStage
    status: EvaluationMeasurementStatus
    run_id: str | None = None
    health_metrics: list[EvaluationMetric] = Field(default_factory=list)
    quality_metrics: list[EvaluationMetric] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)


class PipelineEvaluationScorecard(BaseModel):
    id: str = Field(default_factory=lambda: f"scorecard-{uuid4().hex[:10]}")
    case_id: str
    gold_version: str
    evaluator_version: str
    condition: EvaluationCondition
    stage_results: list[StageEvaluationResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PairedAblationDelta(BaseModel):
    id: str = Field(default_factory=lambda: f"comparison-{uuid4().hex[:10]}")
    case_id: str
    stage: PipelineStage
    metric_name: str
    full_condition_id: str
    ablation_condition_id: str
    status: EvaluationMeasurementStatus
    full_value: float | None = None
    ablation_value: float | None = None
    delta: float | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_delta(self) -> PairedAblationDelta:
        values = (self.full_value, self.ablation_value, self.delta)
        if self.status == EvaluationMeasurementStatus.MEASURED:
            if any(value is None for value in values):
                raise ValueError("measured deltas require both values and delta")
        elif any(value is not None for value in values):
            raise ValueError("unmeasured deltas cannot have numeric values")
        return self
