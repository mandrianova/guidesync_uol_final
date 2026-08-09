from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .documentation_evaluation import GeneratedClaimSupport
from .evaluation import (
    EvaluationAdjudicationStatus,
    EvaluationMeasurementStatus,
    EvaluationMetric,
    UiEvidenceModality,
)
from .evidence import (
    ScreenshotAction,
    ScreenshotActionKind,
    ScreenshotLocatorKind,
    ScreenshotTheme,
    ScreenshotViewport,
)


class UiCaptureStatus(StrEnum):
    CAPTURED = "captured"
    FAILED = "failed"


class UiVisualFactKind(StrEnum):
    VISIBILITY = "visibility"
    ICON_STATE = "icon_state"
    THEME = "theme"
    HIERARCHY = "hierarchy"
    RESPONSIVE_BEHAVIOR = "responsive_behavior"


class UiCaptureChecks(BaseModel):
    route: str
    viewport: ScreenshotViewport
    theme: ScreenshotTheme
    state: str = Field(min_length=1)
    require_non_blank: bool = True


class VersionedUiScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    schema_version: str = "1.0"
    build_identity: str = Field(min_length=1)
    route: str = Field(min_length=1)
    viewport: ScreenshotViewport
    theme: ScreenshotTheme
    requested_state: str = Field(min_length=1)
    actions: list[ScreenshotAction] = Field(default_factory=list, max_length=8)
    checks: UiCaptureChecks
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_bounded_scenario(self) -> VersionedUiScenario:
        if not self.route.startswith("/") or self.route.startswith("//"):
            raise ValueError("UI evaluation routes must be root-relative")
        if self.theme is ScreenshotTheme.SYSTEM:
            raise ValueError("UI evaluation scenarios require an explicit theme")
        expected = (
            self.route,
            self.viewport,
            self.theme,
            self.requested_state,
        )
        observed = (
            self.checks.route,
            self.checks.viewport,
            self.checks.theme,
            self.checks.state,
        )
        if observed != expected:
            raise ValueError("UI capture checks must match the declared scenario")
        for action in self.actions:
            if action.kind not in {
                ScreenshotActionKind.CLICK,
                ScreenshotActionKind.WAIT_FOR,
            }:
                raise ValueError(
                    "UI evaluation actions are limited to named ARIA click/wait controls"
                )
            if (
                action.locator_kind is not ScreenshotLocatorKind.ROLE
                or not action.role_name
            ):
                raise ValueError("UI evaluation actions require a named ARIA role")
            if action.route is not None or action.wait_ms is not None:
                raise ValueError(
                    "UI evaluation actions cannot include navigation or timed waits"
                )
        return self


class FrozenUiArtifactManifest(BaseModel):
    scenario_id: str
    status: UiCaptureStatus
    route: str = ""
    viewport: ScreenshotViewport | None = None
    theme: ScreenshotTheme | None = None
    observed_state: str = ""
    browser_identity: str | None = None
    build_identity: str | None = None
    blank: bool = False
    png_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    png_artifact_ref: str | None = None
    dom_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    dom_artifact_ref: str | None = None
    aria_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    aria_artifact_ref: str | None = None
    captured_at: datetime | None = None
    errors: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_capture_artifacts(self) -> FrozenUiArtifactManifest:
        pairs = (
            (self.png_sha256, self.png_artifact_ref),
            (self.dom_sha256, self.dom_artifact_ref),
            (self.aria_sha256, self.aria_artifact_ref),
        )
        if any((checksum is None) != (reference is None) for checksum, reference in pairs):
            raise ValueError("UI artifact checksums and refs must be present together")
        if self.status is UiCaptureStatus.CAPTURED:
            required = (
                self.route,
                self.viewport,
                self.theme,
                self.observed_state,
                self.browser_identity,
                self.build_identity,
                self.png_sha256,
                self.png_artifact_ref,
                self.dom_sha256,
                self.dom_artifact_ref,
                self.aria_sha256,
                self.aria_artifact_ref,
                self.captured_at,
            )
            if any(value is None or value == "" for value in required):
                raise ValueError("captured UI artifacts require complete frozen provenance")
        elif not self.errors:
            raise ValueError("failed UI captures require at least one error")
        return self


class FrozenUiEvidenceManifest(BaseModel):
    schema_version: str = "1.0"
    scenarios: list[VersionedUiScenario] = Field(min_length=1)
    artifacts: list[FrozenUiArtifactManifest] = Field(min_length=1)
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_scenario_artifacts(self) -> FrozenUiEvidenceManifest:
        scenario_ids = [scenario.id for scenario in self.scenarios]
        artifact_ids = [artifact.scenario_id for artifact in self.artifacts]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("UI scenario ids must be unique")
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("UI artifact scenario ids must be unique")
        if set(scenario_ids) != set(artifact_ids):
            raise ValueError("every frozen UI scenario requires exactly one artifact record")
        return self


class UiVisualGoldFact(BaseModel):
    id: str
    scenario_id: str
    kind: UiVisualFactKind
    statement: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    obligation_ids: list[str] = Field(default_factory=list)
    adjudication_status: EvaluationAdjudicationStatus


class UiEvidenceGold(BaseModel):
    case_id: str
    version: str
    facts: list[UiVisualGoldFact] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_gold_facts(self) -> UiEvidenceGold:
        fact_ids = [fact.id for fact in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("UI gold fact ids must be unique")
        return self


class UiPredictedVisualClaim(BaseModel):
    id: str
    statement: str = Field(min_length=1)
    support: GeneratedClaimSupport
    matched_gold_fact_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class UiScenarioPrediction(BaseModel):
    scenario_id: str
    predicted_state: str = Field(min_length=1)
    claims: list[UiPredictedVisualClaim] = Field(default_factory=list)


class ConditionedUiEvidenceItem(BaseModel):
    scenario_id: str
    route: str
    viewport: ScreenshotViewport
    theme: ScreenshotTheme
    observed_state: str
    dom_sha256: str | None = None
    dom_artifact_ref: str | None = None
    aria_sha256: str | None = None
    aria_artifact_ref: str | None = None
    png_sha256: str | None = None
    png_artifact_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class ConditionedUiEvidence(BaseModel):
    modality: UiEvidenceModality
    applied_condition_checksum: str
    items: list[ConditionedUiEvidenceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_modality_boundary(self) -> ConditionedUiEvidence:
        scenario_ids = [item.scenario_id for item in self.items]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("conditioned UI evidence scenario ids must be unique")
        if self.modality is UiEvidenceModality.NONE:
            if self.items:
                raise ValueError("the no-UI condition cannot expose UI evidence items")
            return self
        for item in self.items:
            validate_conditioned_item(item, self.modality)
        return self


def validate_conditioned_item(
    item: ConditionedUiEvidenceItem,
    modality: UiEvidenceModality,
) -> None:
    dom_aria = (
        item.dom_sha256,
        item.dom_artifact_ref,
        item.aria_sha256,
        item.aria_artifact_ref,
    )
    if any(value is None for value in dom_aria):
        raise ValueError("DOM/ARIA conditions require both frozen snapshots")
    png = (item.png_sha256, item.png_artifact_ref)
    if modality is UiEvidenceModality.DOM_ARIA and any(
        value is not None for value in png
    ):
        raise ValueError("the DOM/ARIA condition cannot expose PNG evidence")
    if modality is UiEvidenceModality.DOM_ARIA_PNG and any(
        value is None for value in png
    ):
        raise ValueError("the full UI condition requires PNG evidence")
    expected_refs = [item.dom_artifact_ref, item.aria_artifact_ref]
    if modality is UiEvidenceModality.DOM_ARIA_PNG:
        expected_refs.append(item.png_artifact_ref)
    if item.evidence_refs != expected_refs:
        raise ValueError("conditioned UI evidence refs must match the declared modality")


class UiEvidenceEvaluationInput(BaseModel):
    case_id: str
    condition_id: str
    expected_condition_checksum: str
    manifest: FrozenUiEvidenceManifest
    gold: UiEvidenceGold
    evidence: ConditionedUiEvidence
    predictions: list[UiScenarioPrediction] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_case_identity(self) -> UiEvidenceEvaluationInput:
        if self.gold.case_id != self.case_id:
            raise ValueError("UI gold case id must match the evaluation input")
        if self.evidence.applied_condition_checksum != self.expected_condition_checksum:
            raise ValueError("applied UI evidence condition checksum does not match")
        scenario_ids = {scenario.id for scenario in self.manifest.scenarios}
        unknown_gold_scenarios = {
            fact.scenario_id for fact in self.gold.facts
        }.difference(scenario_ids)
        if unknown_gold_scenarios:
            raise ValueError("UI gold facts must reference frozen manifest scenarios")
        captured = {
            artifact.scenario_id: artifact
            for artifact in self.manifest.artifacts
            if artifact.status is UiCaptureStatus.CAPTURED
        }
        evidence_by_scenario = {
            item.scenario_id: item for item in self.evidence.items
        }
        expected_evidence_ids = (
            set() if self.evidence.modality is UiEvidenceModality.NONE else set(captured)
        )
        if set(evidence_by_scenario) != expected_evidence_ids:
            raise ValueError("conditioned UI evidence must project every frozen capture")
        for scenario_id, item in evidence_by_scenario.items():
            artifact = captured[scenario_id]
            expected = (
                artifact.route,
                artifact.viewport,
                artifact.theme,
                artifact.observed_state,
                artifact.dom_sha256,
                artifact.dom_artifact_ref,
                artifact.aria_sha256,
                artifact.aria_artifact_ref,
                artifact.png_sha256
                if self.evidence.modality is UiEvidenceModality.DOM_ARIA_PNG
                else None,
                artifact.png_artifact_ref
                if self.evidence.modality is UiEvidenceModality.DOM_ARIA_PNG
                else None,
            )
            observed = (
                item.route,
                item.viewport,
                item.theme,
                item.observed_state,
                item.dom_sha256,
                item.dom_artifact_ref,
                item.aria_sha256,
                item.aria_artifact_ref,
                item.png_sha256,
                item.png_artifact_ref,
            )
            if observed != expected:
                raise ValueError("conditioned UI evidence must match frozen artifacts")
        prediction_ids = [prediction.scenario_id for prediction in self.predictions]
        if len(prediction_ids) != len(set(prediction_ids)):
            raise ValueError("UI scenario predictions must be unique")
        return self


class UiAcquisitionCounts(BaseModel):
    requested: int = Field(ge=0)
    captured: int = Field(ge=0)
    valid: int = Field(ge=0)
    failed: int = Field(ge=0)
    blank: int = Field(ge=0)
    wrong_route: int = Field(ge=0)
    wrong_viewport: int = Field(ge=0)
    wrong_theme: int = Field(ge=0)
    wrong_state: int = Field(ge=0)
    wrong_build: int = Field(ge=0)


class UiVisualClaimCounts(BaseModel):
    total: int = Field(ge=0)
    supported: int = Field(ge=0)
    contradicted: int = Field(ge=0)
    not_enough_evidence: int = Field(ge=0)
    gold_facts: int = Field(ge=0)
    covered_gold_facts: int = Field(ge=0)
    evidence_linked: int = Field(ge=0)


class UiEvidenceEvaluationReport(BaseModel):
    case_id: str
    condition_id: str
    modality: UiEvidenceModality
    manifest_checksum: str | None = None
    acquisition_status: EvaluationMeasurementStatus
    interpretation_status: EvaluationMeasurementStatus
    acquisition_counts: UiAcquisitionCounts
    claim_counts: UiVisualClaimCounts
    health_metrics: list[EvaluationMetric] = Field(default_factory=list)
    quality_metrics: list[EvaluationMetric] = Field(default_factory=list)
    invalid_scenario_ids: list[str] = Field(default_factory=list)
    unevaluated_prediction_ids: list[str] = Field(default_factory=list)
    unsupported_claim_ids: list[str] = Field(default_factory=list)
    contradicted_claim_ids: list[str] = Field(default_factory=list)
    not_enough_evidence_claim_ids: list[str] = Field(default_factory=list)
    missed_gold_fact_ids: list[str] = Field(default_factory=list)
    invalid_evidence_refs: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
