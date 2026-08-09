from __future__ import annotations

from guidesync_agent.schemas import (
    EvaluationMeasurementStatus,
    EvaluationMetric,
    FrozenUiArtifactManifest,
    GeneratedClaimSupport,
    PipelineStage,
    StageEvaluationResult,
    UiAcquisitionCounts,
    UiCaptureStatus,
    UiEvidenceEvaluationInput,
    UiEvidenceEvaluationReport,
    UiEvidenceModality,
    UiScenarioPrediction,
    UiVisualClaimCounts,
    VersionedUiScenario,
)
from guidesync_agent.services.evaluation_adjudication import is_scorable_gold
from guidesync_agent.services.evaluation_metrics import (
    f_beta_from_metrics,
    not_evaluated_metric,
    ratio_metric,
)
from guidesync_agent.services.evaluation_ui_manifest import (
    validate_ui_evidence_manifest,
)

UI_QUALITY_METRIC_NAMES = (
    "visual_fact_precision",
    "visual_fact_recall",
    "visual_fact_f1",
    "state_classification_accuracy",
    "evidence_coverage",
    "unsupported_visual_claim_rate",
    "contradicted_visual_claim_rate",
    "not_enough_evidence_visual_claim_rate",
)


def evaluate_ui_evidence(
    evaluation_input: UiEvidenceEvaluationInput,
) -> UiEvidenceEvaluationReport:
    validate_ui_evidence_manifest(evaluation_input.manifest)
    scenarios = {item.id: item for item in evaluation_input.manifest.scenarios}
    artifacts = {
        item.scenario_id: item for item in evaluation_input.manifest.artifacts
    }
    acquisition_counts, invalid_scenarios = acquisition_result(scenarios, artifacts)
    acquisition_status = (
        EvaluationMeasurementStatus.MEASURED
        if acquisition_counts.valid == acquisition_counts.requested
        else EvaluationMeasurementStatus.FAILED
    )
    health_metrics = acquisition_metrics(acquisition_counts)

    valid_scenarios = set(scenarios).difference(invalid_scenarios)
    predictions = {
        item.scenario_id: item for item in evaluation_input.predictions
    }
    unevaluated_predictions = sorted(set(predictions).difference(valid_scenarios))
    if (
        evaluation_input.evidence.modality is UiEvidenceModality.NONE
        or not valid_scenarios
    ):
        reason = (
            "condition provides no UI evidence"
            if evaluation_input.evidence.modality is UiEvidenceModality.NONE
            else "no UI scenario passed the acquisition gate"
        )
        return UiEvidenceEvaluationReport(
            case_id=evaluation_input.case_id,
            condition_id=evaluation_input.condition_id,
            modality=evaluation_input.evidence.modality,
            manifest_checksum=evaluation_input.manifest.checksum,
            acquisition_status=acquisition_status,
            interpretation_status=EvaluationMeasurementStatus.NOT_EVALUATED,
            acquisition_counts=acquisition_counts,
            claim_counts=empty_claim_counts(evaluation_input, valid_scenarios),
            health_metrics=health_metrics,
            quality_metrics=[
                not_evaluated_metric(name, reason)
                for name in UI_QUALITY_METRIC_NAMES
            ],
            invalid_scenario_ids=sorted(invalid_scenarios),
            unevaluated_prediction_ids=unevaluated_predictions,
            findings=[reason],
        )

    return interpreted_report(
        evaluation_input,
        scenarios,
        valid_scenarios,
        predictions,
        acquisition_counts,
        acquisition_status,
        health_metrics,
        unevaluated_predictions,
    )


def acquisition_result(
    scenarios: dict[str, VersionedUiScenario],
    artifacts: dict[str, FrozenUiArtifactManifest],
) -> tuple[UiAcquisitionCounts, set[str]]:
    captured = failed = blank = 0
    wrong_route = wrong_viewport = wrong_theme = wrong_state = wrong_build = 0
    invalid: set[str] = set()
    for scenario_id, scenario in scenarios.items():
        artifact = artifacts[scenario_id]
        if artifact.status is UiCaptureStatus.FAILED:
            failed += 1
            invalid.add(scenario_id)
            continue
        captured += 1
        route_mismatch = artifact.route != scenario.checks.route
        viewport_mismatch = artifact.viewport != scenario.checks.viewport
        theme_mismatch = artifact.theme != scenario.checks.theme
        state_mismatch = normalized_state(artifact.observed_state) != normalized_state(
            scenario.checks.state
        )
        build_mismatch = artifact.build_identity != scenario.build_identity
        is_blank = artifact.blank and scenario.checks.require_non_blank
        wrong_route += int(route_mismatch)
        wrong_viewport += int(viewport_mismatch)
        wrong_theme += int(theme_mismatch)
        wrong_state += int(state_mismatch)
        wrong_build += int(build_mismatch)
        blank += int(is_blank)
        if any(
            (
                route_mismatch,
                viewport_mismatch,
                theme_mismatch,
                state_mismatch,
                build_mismatch,
                is_blank,
            )
        ):
            invalid.add(scenario_id)
    counts = UiAcquisitionCounts(
        requested=len(scenarios),
        captured=captured,
        valid=len(scenarios) - len(invalid),
        failed=failed,
        blank=blank,
        wrong_route=wrong_route,
        wrong_viewport=wrong_viewport,
        wrong_theme=wrong_theme,
        wrong_state=wrong_state,
        wrong_build=wrong_build,
    )
    return counts, invalid


def acquisition_metrics(counts: UiAcquisitionCounts) -> list[EvaluationMetric]:
    return [
        ratio_metric("capture_coverage", counts.captured, counts.requested),
        ratio_metric("scenario_coverage", counts.valid, counts.requested),
        ratio_metric(
            "route_accuracy",
            counts.requested - counts.failed - counts.wrong_route,
            counts.requested,
        ),
        ratio_metric(
            "viewport_accuracy",
            counts.requested - counts.failed - counts.wrong_viewport,
            counts.requested,
        ),
        ratio_metric(
            "theme_accuracy",
            counts.requested - counts.failed - counts.wrong_theme,
            counts.requested,
        ),
        ratio_metric(
            "requested_state_accuracy",
            counts.requested - counts.failed - counts.wrong_state,
            counts.requested,
        ),
        ratio_metric(
            "build_identity_accuracy",
            counts.requested - counts.failed - counts.wrong_build,
            counts.requested,
        ),
        ratio_metric("blank_capture_rate", counts.blank, counts.captured),
    ]


def interpreted_report(  # noqa: PLR0913 - assembles one typed stage report
    evaluation_input: UiEvidenceEvaluationInput,
    scenarios: dict[str, VersionedUiScenario],
    valid_scenarios: set[str],
    predictions: dict[str, UiScenarioPrediction],
    acquisition_counts: UiAcquisitionCounts,
    acquisition_status: EvaluationMeasurementStatus,
    health_metrics: list[EvaluationMetric],
    unevaluated_predictions: list[str],
) -> UiEvidenceEvaluationReport:
    gold_facts = {
        fact.id: fact
        for fact in evaluation_input.gold.facts
        if fact.scenario_id in valid_scenarios
        and is_scorable_gold(fact.adjudication_status)
    }
    claims = [
        (prediction, claim)
        for scenario_id, prediction in predictions.items()
        if scenario_id in valid_scenarios
        for claim in prediction.claims
    ]
    supported = [item for item in claims if item[1].support is GeneratedClaimSupport.SUPPORTED]
    contradicted = [
        item for item in claims if item[1].support is GeneratedClaimSupport.CONTRADICTED
    ]
    not_enough = [
        item
        for item in claims
        if item[1].support is GeneratedClaimSupport.NOT_ENOUGH_EVIDENCE
    ]
    covered_facts: set[str] = set()
    invalid_evidence_refs: set[str] = set()
    evidence_linked = 0
    evidence_by_scenario = {
        item.scenario_id: set(item.evidence_refs)
        for item in evaluation_input.evidence.items
    }
    for prediction, claim in claims:
        allowed_refs = evidence_by_scenario.get(prediction.scenario_id, set())
        supplied_refs = set(claim.evidence_refs)
        if supplied_refs and supplied_refs.issubset(allowed_refs):
            evidence_linked += 1
        invalid_evidence_refs.update(supplied_refs.difference(allowed_refs))
        if claim.support is not GeneratedClaimSupport.SUPPORTED:
            continue
        covered_facts.update(
            fact_id
            for fact_id in claim.matched_gold_fact_ids
            if fact_id in gold_facts
            and gold_facts[fact_id].scenario_id == prediction.scenario_id
        )

    precision = ratio_metric("visual_fact_precision", len(supported), len(claims))
    recall = ratio_metric("visual_fact_recall", len(covered_facts), len(gold_facts))
    correct_states = sum(
        normalized_state(predictions[scenario_id].predicted_state)
        == normalized_state(scenarios[scenario_id].requested_state)
        for scenario_id in valid_scenarios
        if scenario_id in predictions
    )
    quality_metrics = [
        precision,
        recall,
        f_beta_from_metrics(precision, recall, name="visual_fact_f1"),
        ratio_metric(
            "state_classification_accuracy",
            correct_states,
            len(valid_scenarios),
        ),
        ratio_metric("evidence_coverage", evidence_linked, len(claims)),
        ratio_metric(
            "unsupported_visual_claim_rate",
            len(contradicted) + len(not_enough),
            len(claims),
        ),
        ratio_metric(
            "contradicted_visual_claim_rate",
            len(contradicted),
            len(claims),
        ),
        ratio_metric(
            "not_enough_evidence_visual_claim_rate",
            len(not_enough),
            len(claims),
        ),
    ]
    return UiEvidenceEvaluationReport(
        case_id=evaluation_input.case_id,
        condition_id=evaluation_input.condition_id,
        modality=evaluation_input.evidence.modality,
        manifest_checksum=evaluation_input.manifest.checksum,
        acquisition_status=acquisition_status,
        interpretation_status=EvaluationMeasurementStatus.MEASURED,
        acquisition_counts=acquisition_counts,
        claim_counts=UiVisualClaimCounts(
            total=len(claims),
            supported=len(supported),
            contradicted=len(contradicted),
            not_enough_evidence=len(not_enough),
            gold_facts=len(gold_facts),
            covered_gold_facts=len(covered_facts),
            evidence_linked=evidence_linked,
        ),
        health_metrics=health_metrics,
        quality_metrics=quality_metrics,
        invalid_scenario_ids=sorted(
            set(scenarios).difference(valid_scenarios)
        ),
        unevaluated_prediction_ids=unevaluated_predictions,
        unsupported_claim_ids=sorted(
            item[1].id for item in [*contradicted, *not_enough]
        ),
        contradicted_claim_ids=sorted(item[1].id for item in contradicted),
        not_enough_evidence_claim_ids=sorted(item[1].id for item in not_enough),
        missed_gold_fact_ids=sorted(set(gold_facts).difference(covered_facts)),
        invalid_evidence_refs=sorted(invalid_evidence_refs),
    )


def empty_claim_counts(
    evaluation_input: UiEvidenceEvaluationInput,
    valid_scenarios: set[str],
) -> UiVisualClaimCounts:
    return UiVisualClaimCounts(
        total=0,
        supported=0,
        contradicted=0,
        not_enough_evidence=0,
        gold_facts=sum(
            fact.scenario_id in valid_scenarios
            and is_scorable_gold(fact.adjudication_status)
            for fact in evaluation_input.gold.facts
        ),
        covered_gold_facts=0,
        evidence_linked=0,
    )


def ui_stage_result(
    report: UiEvidenceEvaluationReport,
    *,
    run_id: str | None = None,
) -> StageEvaluationResult:
    status = (
        report.acquisition_status
        if report.acquisition_status is EvaluationMeasurementStatus.FAILED
        else report.interpretation_status
    )
    return StageEvaluationResult(
        case_id=report.case_id,
        condition_id=report.condition_id,
        stage=PipelineStage.UI_EVIDENCE,
        status=status,
        run_id=run_id,
        health_metrics=report.health_metrics,
        quality_metrics=report.quality_metrics,
        findings=report.findings,
    )


def normalized_state(value: str) -> str:
    return " ".join(value.casefold().split())
