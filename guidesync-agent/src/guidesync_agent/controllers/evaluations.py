from __future__ import annotations

from guidesync_agent.schemas import (
    AblationComparisonReport,
    EvaluationComparisonPage,
    EvaluationComparisonRecord,
    EvaluationExperimentManifest,
    EvaluationExperimentPage,
    EvaluationExperimentRecord,
    EvaluationExperimentRun,
    EvaluationRunPage,
    EvaluationRunRecord,
    EvaluationRunStatus,
)
from guidesync_agent.services import evaluation_records
from guidesync_agent.storage import (
    create_evaluation_store,
    create_project_store,
)


def create_experiment(
    project_id: str,
    manifest: EvaluationExperimentManifest,
) -> EvaluationExperimentRecord | None:
    if create_project_store().get(project_id) is None:
        return None
    return evaluation_records.save_experiment(
        create_evaluation_store(),
        project_id=project_id,
        manifest=manifest,
    )


def list_project_experiments(
    project_id: str,
    *,
    limit: int,
    offset: int,
) -> EvaluationExperimentPage | None:
    if create_project_store().get(project_id) is None:
        return None
    return evaluation_records.list_experiments(
        create_evaluation_store(),
        project_id,
        limit=limit,
        offset=offset,
    )


def get_experiment(experiment_id: str) -> EvaluationExperimentRecord | None:
    return create_evaluation_store().get_experiment(experiment_id)


def save_run(
    experiment_id: str,
    run: EvaluationExperimentRun,
) -> EvaluationRunRecord:
    return evaluation_records.save_run(
        create_evaluation_store(),
        experiment_id=experiment_id,
        run=run,
    )


def list_runs(
    experiment_id: str,
    *,
    case_id: str | None,
    condition_id: str | None,
    status: EvaluationRunStatus | None,
    limit: int,
    offset: int,
) -> EvaluationRunPage:
    return evaluation_records.list_runs(
        create_evaluation_store(),
        experiment_id,
        case_id=case_id,
        condition_id=condition_id,
        status=status,
        limit=limit,
        offset=offset,
    )


def save_comparison(
    experiment_id: str,
    report: AblationComparisonReport,
) -> EvaluationComparisonRecord:
    return evaluation_records.save_comparison(
        create_evaluation_store(),
        experiment_id=experiment_id,
        report=report,
    )


def list_comparisons(
    experiment_id: str,
    *,
    limit: int,
    offset: int,
) -> EvaluationComparisonPage:
    return evaluation_records.list_comparisons(
        create_evaluation_store(),
        experiment_id,
        limit=limit,
        offset=offset,
    )
