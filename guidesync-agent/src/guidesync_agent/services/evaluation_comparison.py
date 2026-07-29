from __future__ import annotations

import random
from collections.abc import Sequence

from guidesync_agent.schemas import (
    AblationComparisonReport,
    EvaluationConditionKind,
    EvaluationExperimentManifest,
    EvaluationExperimentRun,
    EvaluationMeasurementStatus,
    EvaluationMetric,
    EvaluationMetricGroup,
    EvaluationMetricSelector,
    EvaluationRunManifest,
    EvaluationRunStatus,
    PairedMetricConfidenceInterval,
    PairedMetricObservation,
    PipelineEvaluationScorecard,
)
from guidesync_agent.services.evaluation_experiment import (
    build_run_manifests,
    full_condition,
    validate_experiment_integrity,
)
from guidesync_agent.services.evaluation_manifest_utils import (
    stable_hash,
    stable_seed,
)
from guidesync_agent.services.evaluation_metrics import (
    failed_metric,
    not_evaluated_metric,
    paired_ablation_delta,
)


def compare_ablation_runs(
    *,
    experiment: EvaluationExperimentManifest,
    runs: Sequence[EvaluationExperimentRun],
    ablation_condition_id: str,
    selectors: Sequence[EvaluationMetricSelector],
) -> AblationComparisonReport:
    validate_experiment_integrity(experiment)
    protocols = {
        protocol.condition.id: protocol for protocol in experiment.conditions
    }
    full = full_condition(experiment)
    ablation = protocols[ablation_condition_id]
    if ablation.condition.kind != EvaluationConditionKind.ABLATION:
        raise ValueError(f"{ablation_condition_id} is not an ablation condition")
    validate_runs_against_experiment(
        experiment,
        runs,
        condition_ids={full.condition.id, ablation.condition.id},
    )

    full_runs = runs_by_pair(runs, full.condition.id)
    ablation_runs = runs_by_pair(runs, ablation.condition.id)
    expected_case_ids = set(ablation.bounded_case_ids) or {
        case.id for case in experiment.cases
    }
    expected_pairs = {
        (case_id, repetition)
        for case_id in expected_case_ids
        for repetition in range(1, experiment.repetitions + 1)
    }
    observations: list[PairedMetricObservation] = []
    excluded_pair_ids: list[str] = []
    warnings: list[str] = []
    for pair in sorted(expected_pairs):
        pair_id = f"{pair[0]}:r{pair[1]}"
        full_run = full_runs.get(pair)
        ablation_run = ablation_runs.get(pair)
        exclusion = pair_exclusion_reason(full_run, ablation_run)
        if exclusion:
            excluded_pair_ids.append(pair_id)
            warnings.append(f"{pair_id}: {exclusion}")
            continue
        if full_run is None or ablation_run is None:
            raise AssertionError("validated pairs must contain both runs")
        validate_paired_manifests(full_run.manifest, ablation_run.manifest)
        observations.extend(
            paired_observations(
                pair=pair,
                pair_id=pair_id,
                full_run=full_run,
                ablation_run=ablation_run,
                selectors=selectors,
            )
        )

    intervals = [
        confidence_interval(
            selector=selector,
            observations=observations,
            experiment=experiment,
            ablation_condition_id=ablation.condition.id,
        )
        for selector in selectors
    ]
    if len(expected_pairs) - len(excluded_pair_ids) < 2:
        warnings.append(
            "Fewer than two completed pairs are descriptive only and cannot "
            "support a general necessity claim."
        )
    return AblationComparisonReport(
        experiment_id=experiment.id,
        full_condition_id=full.condition.id,
        ablation_condition_id=ablation.condition.id,
        observations=observations,
        intervals=intervals,
        excluded_pair_ids=excluded_pair_ids,
        warnings=warnings,
    )


def paired_observations(
    *,
    pair: tuple[str, int],
    pair_id: str,
    full_run: EvaluationExperimentRun,
    ablation_run: EvaluationExperimentRun,
    selectors: Sequence[EvaluationMetricSelector],
) -> list[PairedMetricObservation]:
    observations: list[PairedMetricObservation] = []
    for selector in selectors:
        full_metric = selected_metric(full_run.scorecard, selector)
        ablation_metric = selected_metric(ablation_run.scorecard, selector)
        delta = paired_ablation_delta(
            case_id=pair[0],
            stage=selector.stage,
            metric_name=selector.metric_name,
            full_condition_id=full_run.manifest.condition_id,
            ablation_condition_id=ablation_run.manifest.condition_id,
            full_metric=full_metric,
            ablation_metric=ablation_metric,
        ).model_copy(
            update={"id": f"comparison-{stable_hash(pair_id, selector.key)[:16]}"}
        )
        observations.append(
            PairedMetricObservation(
                case_id=pair[0],
                repetition=pair[1],
                full_run_id=full_run.manifest.id,
                ablation_run_id=ablation_run.manifest.id,
                selector=selector,
                delta=delta,
            )
        )
    return observations


def validate_paired_manifests(
    full: EvaluationRunManifest,
    ablation: EvaluationRunManifest,
) -> None:
    comparable = (
        full.experiment_id == ablation.experiment_id,
        full.case_id == ablation.case_id,
        full.repetition == ablation.repetition,
        full.case_checksum == ablation.case_checksum,
        full.configuration_checksum == ablation.configuration_checksum,
        full.experiment_checksum == ablation.experiment_checksum,
    )
    if not all(comparable):
        raise ValueError("paired runs do not share identical frozen inputs")


def selected_metric(
    scorecard: PipelineEvaluationScorecard | None,
    selector: EvaluationMetricSelector,
) -> EvaluationMetric:
    if scorecard is None:
        return not_evaluated_metric(selector.metric_name, "scorecard is unavailable")
    stage_results = [
        result for result in scorecard.stage_results if result.stage == selector.stage
    ]
    if len(stage_results) != 1:
        return failed_metric(
            selector.metric_name,
            f"expected one {selector.stage.value} stage result, found "
            f"{len(stage_results)}",
        )
    metrics = (
        stage_results[0].health_metrics
        if selector.group == EvaluationMetricGroup.HEALTH
        else stage_results[0].quality_metrics
    )
    matches = [metric for metric in metrics if metric.name == selector.metric_name]
    if not matches:
        return not_evaluated_metric(
            selector.metric_name,
            f"{selector.key} was not recorded",
        )
    if len(matches) > 1:
        return failed_metric(
            selector.metric_name,
            f"{selector.key} was recorded more than once",
        )
    return matches[0]


def confidence_interval(
    *,
    selector: EvaluationMetricSelector,
    observations: Sequence[PairedMetricObservation],
    experiment: EvaluationExperimentManifest,
    ablation_condition_id: str,
) -> PairedMetricConfidenceInterval:
    measured = [
        observation
        for observation in observations
        if observation.selector == selector
        and observation.delta.status == EvaluationMeasurementStatus.MEASURED
        and observation.delta.delta is not None
    ]
    if not measured:
        return PairedMetricConfidenceInterval(
            selector=selector,
            status=EvaluationMeasurementStatus.NOT_EVALUATED,
            paired_count=0,
            case_count=0,
            confidence_level=experiment.confidence_level,
            bootstrap_iterations=0,
            warnings=["no measured full-versus-ablation pairs"],
        )
    values_by_case: dict[str, list[float]] = {}
    for observation in measured:
        delta = observation.delta.delta
        if delta is None:
            raise AssertionError("measured deltas must contain values")
        values_by_case.setdefault(observation.case_id, []).append(delta)
    case_means = [
        sum(case_values) / len(case_values)
        for case_values in values_by_case.values()
    ]
    mean_delta, lower, upper = bootstrap_mean_interval(
        case_means,
        iterations=experiment.bootstrap_iterations,
        confidence_level=experiment.confidence_level,
        seed=stable_seed(
            experiment.random_seed,
            ablation_condition_id,
            selector.key,
        ),
    )
    warnings = (
        ["one case gives a descriptive delta, not a general uncertainty estimate"]
        if len(case_means) == 1
        else []
    )
    return PairedMetricConfidenceInterval(
        selector=selector,
        status=EvaluationMeasurementStatus.MEASURED,
        paired_count=len(measured),
        case_count=len(case_means),
        mean_delta=mean_delta,
        lower_bound=lower,
        upper_bound=upper,
        confidence_level=experiment.confidence_level,
        bootstrap_iterations=experiment.bootstrap_iterations,
        warnings=warnings,
    )


def bootstrap_mean_interval(
    values: Sequence[float],
    *,
    iterations: int,
    confidence_level: float,
    seed: int,
) -> tuple[float, float, float]:
    if not values:
        raise ValueError("bootstrap requires at least one paired delta")
    rng = random.Random(seed)
    sample_size = len(values)
    bootstrap_means = sorted(
        sum(rng.choice(values) for _ in range(sample_size)) / sample_size
        for _ in range(iterations)
    )
    alpha = (1 - confidence_level) / 2
    return (
        sum(values) / sample_size,
        percentile(bootstrap_means, alpha),
        percentile(bootstrap_means, 1 - alpha),
    )


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    position = (len(values) - 1) * quantile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(values) - 1)
    weight = position - lower_index
    return values[lower_index] * (1 - weight) + values[upper_index] * weight


def pair_exclusion_reason(
    full: EvaluationExperimentRun | None,
    ablation: EvaluationExperimentRun | None,
) -> str | None:
    if full is None:
        return "full run is missing"
    if ablation is None:
        return "ablation run is missing"
    if full.status == EvaluationRunStatus.FAILED:
        return f"full run failed: {full.failure}"
    if ablation.status == EvaluationRunStatus.FAILED:
        return f"ablation run failed: {ablation.failure}"
    return None


def runs_by_pair(
    runs: Sequence[EvaluationExperimentRun],
    condition_id: str,
) -> dict[tuple[str, int], EvaluationExperimentRun]:
    result: dict[tuple[str, int], EvaluationExperimentRun] = {}
    for run in runs:
        if run.manifest.condition_id != condition_id:
            continue
        key = (run.manifest.case_id, run.manifest.repetition)
        if key in result:
            raise ValueError(
                f"duplicate run for {condition_id}, {key[0]}, repetition {key[1]}"
            )
        result[key] = run
    return result


def validate_runs_against_experiment(
    experiment: EvaluationExperimentManifest,
    runs: Sequence[EvaluationExperimentRun],
    *,
    condition_ids: set[str],
) -> None:
    expected = {
        manifest.id: manifest for manifest in build_run_manifests(experiment)
    }
    for run in runs:
        if run.manifest.condition_id not in condition_ids:
            continue
        expected_manifest = expected.get(run.manifest.id)
        if expected_manifest is None or run.manifest != expected_manifest:
            raise ValueError(
                f"{run.manifest.id} does not match the frozen experiment manifest"
            )
