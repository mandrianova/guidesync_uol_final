from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from .evaluation import (
    EvaluationAdjudicationStatus,
    EvaluationCondition,
    EvaluationConditionKind,
    EvaluationMeasurementStatus,
    PairedAblationDelta,
    PipelineEvaluationScorecard,
    PipelineStage,
)
from .model_usage import RunTokenUsageSummary


class EvaluationMetricGroup(StrEnum):
    HEALTH = "health"
    QUALITY = "quality"


class EvaluationRunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class EvaluationCaseManifest(BaseModel):
    id: str
    repository_url: str
    base_commit: str
    head_commit: str
    allowed_paths: list[str] = Field(min_length=1)
    withheld_paths: list[str] = Field(default_factory=list)
    input_checksums: dict[str, str] = Field(min_length=1)
    input_artifact_refs: dict[str, str] = Field(min_length=1)
    index_commit: str
    gold_version: str
    gold_checksum: str
    gold_artifact_ref: str
    gold_adjudication_status: EvaluationAdjudicationStatus = (
        EvaluationAdjudicationStatus.DRAFT
    )

    @model_validator(mode="after")
    def validate_artifact_checksums(self) -> EvaluationCaseManifest:
        if set(self.input_checksums) != set(self.input_artifact_refs):
            raise ValueError(
                "input checksums and artifact refs must name the same frozen inputs"
            )
        ensure_unique(self.allowed_paths, "allowed path")
        ensure_unique(self.withheld_paths, "withheld path")
        return self


class FrozenEvaluationConfiguration(BaseModel):
    application_commit: str
    prompt_checksums: dict[str, str] = Field(min_length=1)
    prompt_artifact_refs: dict[str, str] = Field(min_length=1)
    model_role_configuration_checksum: str
    model_role_configuration_artifact_ref: str
    evaluator_version: str
    runner_version: str

    @model_validator(mode="after")
    def validate_prompt_checksums(self) -> FrozenEvaluationConfiguration:
        if set(self.prompt_checksums) != set(self.prompt_artifact_refs):
            raise ValueError(
                "prompt checksums and artifact refs must name the same prompts"
            )
        return self


class EvaluationConditionProtocol(BaseModel):
    condition: EvaluationCondition
    behavior: str = Field(min_length=1)
    changed_stages: list[PipelineStage] = Field(default_factory=list)
    bounded_case_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scope(self) -> EvaluationConditionProtocol:
        if self.condition.kind == EvaluationConditionKind.FULL:
            if self.changed_stages:
                raise ValueError("the full condition cannot declare changed stages")
        elif self.condition.kind == EvaluationConditionKind.ABLATION:
            removed_stage = self.condition.removed_stage
            if removed_stage is None or self.changed_stages != [removed_stage]:
                raise ValueError(
                    "an ablation must declare exactly its removed stage as changed"
                )
        elif not self.changed_stages:
            raise ValueError("non-full conditions must declare their changed stages")
        return self


class EvaluationExperimentManifest(BaseModel):
    id: str
    cases: list[EvaluationCaseManifest] = Field(min_length=1)
    conditions: list[EvaluationConditionProtocol] = Field(min_length=2)
    configuration: FrozenEvaluationConfiguration
    repetitions: int = Field(default=1, ge=1)
    bootstrap_iterations: int = Field(default=2000, ge=100)
    confidence_level: float = Field(default=0.95, gt=0.0, lt=1.0)
    random_seed: int = Field(default=1729, ge=0)

    @model_validator(mode="after")
    def validate_experiment(self) -> EvaluationExperimentManifest:
        ensure_unique((case.id for case in self.cases), "case id")
        ensure_unique(
            (protocol.condition.id for protocol in self.conditions),
            "condition id",
        )
        full_conditions = [
            protocol
            for protocol in self.conditions
            if protocol.condition.kind == EvaluationConditionKind.FULL
        ]
        if len(full_conditions) != 1:
            raise ValueError("an experiment requires exactly one full condition")
        case_ids = {case.id for case in self.cases}
        for protocol in self.conditions:
            unknown = set(protocol.bounded_case_ids).difference(case_ids)
            if unknown:
                raise ValueError(
                    f"{protocol.condition.id} references unknown bounded cases: "
                    f"{', '.join(sorted(unknown))}"
                )
        return self


class EvaluationRunManifest(BaseModel):
    id: str
    experiment_id: str
    case_id: str
    condition_id: str
    repetition: int = Field(ge=1)
    case_checksum: str
    condition_checksum: str
    configuration_checksum: str
    experiment_checksum: str
    random_seed: int = Field(ge=0)


class EvaluationExecutionResult(BaseModel):
    applied_condition_checksum: str
    scorecard: PipelineEvaluationScorecard
    transcript_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    usage: RunTokenUsageSummary | None = None


class EvaluationExecutionFailure(BaseModel):
    failure: str = Field(min_length=1)
    transcript_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    usage: RunTokenUsageSummary | None = None


class EvaluationExperimentRun(BaseModel):
    manifest: EvaluationRunManifest
    status: EvaluationRunStatus
    scorecard: PipelineEvaluationScorecard | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    transcript_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    usage: RunTokenUsageSummary | None = None
    failure: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> EvaluationExperimentRun:
        if self.status == EvaluationRunStatus.COMPLETED:
            if self.scorecard is None or self.failure is not None:
                raise ValueError("completed runs require a scorecard and no failure")
        elif not self.failure:
            raise ValueError("failed runs require a failure")
        return self


class EvaluationMetricSelector(BaseModel):
    stage: PipelineStage
    group: EvaluationMetricGroup
    metric_name: str

    @property
    def key(self) -> str:
        return f"{self.stage.value}:{self.group.value}:{self.metric_name}"


class PairedMetricObservation(BaseModel):
    case_id: str
    repetition: int
    full_run_id: str
    ablation_run_id: str
    selector: EvaluationMetricSelector
    delta: PairedAblationDelta


class PairedMetricConfidenceInterval(BaseModel):
    selector: EvaluationMetricSelector
    status: EvaluationMeasurementStatus
    paired_count: int = Field(ge=0)
    case_count: int = Field(ge=0)
    mean_delta: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    confidence_level: float
    bootstrap_iterations: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_interval(self) -> PairedMetricConfidenceInterval:
        values = (self.mean_delta, self.lower_bound, self.upper_bound)
        if self.status == EvaluationMeasurementStatus.MEASURED:
            if (
                self.paired_count == 0
                or self.case_count == 0
                or any(value is None for value in values)
            ):
                raise ValueError("measured intervals require paired values and bounds")
        elif any(value is not None for value in values):
            raise ValueError("unmeasured intervals cannot have numeric bounds")
        return self


class AblationComparisonReport(BaseModel):
    experiment_id: str
    full_condition_id: str
    ablation_condition_id: str
    observations: list[PairedMetricObservation] = Field(default_factory=list)
    intervals: list[PairedMetricConfidenceInterval] = Field(default_factory=list)
    excluded_pair_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def ensure_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)
