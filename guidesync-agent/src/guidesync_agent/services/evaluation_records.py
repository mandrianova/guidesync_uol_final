from __future__ import annotations

from guidesync_agent.schemas import (
    AblationComparisonReport,
    EvaluationComparisonPage,
    EvaluationComparisonRecord,
    EvaluationExecutionResult,
    EvaluationExperimentManifest,
    EvaluationExperimentPage,
    EvaluationExperimentRecord,
    EvaluationExperimentRun,
    EvaluationMetricSelector,
    EvaluationRunPage,
    EvaluationRunRecord,
    EvaluationRunStatus,
)
from guidesync_agent.services.evaluation_comparison import compare_ablation_runs
from guidesync_agent.services.evaluation_experiment import (
    build_run_manifests,
    validate_execution_result,
    validate_experiment_integrity,
    validate_scorecard_identity,
)
from guidesync_agent.services.evaluation_manifest_utils import (
    experiment_checksum,
    stable_hash,
)
from guidesync_agent.storage import EvaluationStore


def save_experiment(
    store: EvaluationStore,
    *,
    project_id: str,
    manifest: EvaluationExperimentManifest,
) -> EvaluationExperimentRecord:
    validate_experiment_integrity(manifest)
    return store.save_experiment(
        project_id,
        manifest,
        experiment_checksum(manifest),
    )


def save_run(
    store: EvaluationStore,
    *,
    experiment_id: str,
    run: EvaluationExperimentRun,
) -> EvaluationRunRecord:
    experiment = required_experiment(store, experiment_id)
    expected = {
        manifest.id: manifest for manifest in build_run_manifests(experiment.manifest)
    }.get(run.manifest.id)
    if expected is None or run.manifest != expected:
        raise ValueError("run manifest does not match the frozen experiment")
    if run.manifest.experiment_id != experiment_id:
        raise ValueError("run does not belong to the requested experiment")
    case = next(
        case for case in experiment.manifest.cases if case.id == run.manifest.case_id
    )
    protocol = next(
        protocol
        for protocol in experiment.manifest.conditions
        if protocol.condition.id == run.manifest.condition_id
    )
    if run.scorecard is not None:
        validate_scorecard_identity(
            run.scorecard,
            run.manifest,
            case,
            protocol,
            experiment.manifest.configuration,
        )
    if run.status == EvaluationRunStatus.COMPLETED:
        if run.scorecard is None:
            raise AssertionError("completed evaluation runs require a scorecard")
        validate_execution_result(
            EvaluationExecutionResult(
                applied_condition_checksum=run.manifest.condition_checksum,
                scorecard=run.scorecard,
                transcript_refs=run.transcript_refs,
                artifact_refs=run.artifact_refs,
                usage=run.usage,
            ),
            run.manifest,
            case,
            protocol,
            experiment.manifest.configuration,
        )
    return store.save_run(run)


def save_comparison(
    store: EvaluationStore,
    *,
    experiment_id: str,
    report: AblationComparisonReport,
) -> EvaluationComparisonRecord:
    experiment = required_experiment(store, experiment_id)
    if report.experiment_id != experiment_id:
        raise ValueError("comparison does not belong to the requested experiment")
    selectors = comparison_selectors(report)
    run_page = store.list_runs(
        experiment_id,
        case_id=None,
        condition_id=None,
        status=None,
        limit=10_000,
        offset=0,
    )
    expected = compare_ablation_runs(
        experiment=experiment.manifest,
        runs=[record.run for record in run_page.items],
        ablation_condition_id=report.ablation_condition_id,
        selectors=selectors,
    )
    if expected != report:
        raise ValueError("comparison does not match the persisted paired runs")
    comparison_digest = stable_hash(
        experiment_id,
        report.full_condition_id,
        report.ablation_condition_id,
    )
    comparison_id = f"evaluation-comparison-{comparison_digest[:16]}"
    return store.save_comparison(comparison_id, report)


def required_experiment(
    store: EvaluationStore,
    experiment_id: str,
) -> EvaluationExperimentRecord:
    experiment = store.get_experiment(experiment_id)
    if experiment is None:
        raise LookupError(f"evaluation experiment not found: {experiment_id}")
    return experiment


def list_experiments(
    store: EvaluationStore,
    project_id: str,
    *,
    limit: int,
    offset: int,
) -> EvaluationExperimentPage:
    return store.list_experiments(project_id, limit=limit, offset=offset)


def list_runs(
    store: EvaluationStore,
    experiment_id: str,
    *,
    case_id: str | None,
    condition_id: str | None,
    status: EvaluationRunStatus | None,
    limit: int,
    offset: int,
) -> EvaluationRunPage:
    required_experiment(store, experiment_id)
    return store.list_runs(
        experiment_id,
        case_id=case_id,
        condition_id=condition_id,
        status=status,
        limit=limit,
        offset=offset,
    )


def list_comparisons(
    store: EvaluationStore,
    experiment_id: str,
    *,
    limit: int,
    offset: int,
) -> EvaluationComparisonPage:
    required_experiment(store, experiment_id)
    return store.list_comparisons(experiment_id, limit=limit, offset=offset)


def comparison_selectors(
    report: AblationComparisonReport,
) -> list[EvaluationMetricSelector]:
    selectors: list[EvaluationMetricSelector] = []
    for interval in report.intervals:
        if interval.selector not in selectors:
            selectors.append(interval.selector)
    for observation in report.observations:
        if observation.selector not in selectors:
            selectors.append(observation.selector)
    return selectors
