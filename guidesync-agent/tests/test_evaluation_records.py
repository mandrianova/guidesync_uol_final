from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from storage_test_utils import sqlite_database_url

from guidesync_agent.api import app
from guidesync_agent.schemas import (
    EvaluationCaseManifest,
    EvaluationExperimentRun,
    EvaluationMeasurementStatus,
    EvaluationMetricGroup,
    EvaluationMetricSelector,
    EvaluationRunStatus,
    FrozenEvaluationConfiguration,
    PipelineEvaluationScorecard,
    PipelineStage,
    StageEvaluationResult,
)
from guidesync_agent.services.evaluation_comparison import compare_ablation_runs
from guidesync_agent.services.evaluation_conditions import default_condition_protocols
from guidesync_agent.services.evaluation_experiment import (
    build_experiment_manifest,
    build_run_manifests,
)
from guidesync_agent.services.evaluation_metrics import ratio_metric


def test_evaluation_records_api_persists_and_filters_provenance(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "GUIDESYNC_DATABASE_URL",
        sqlite_database_url(tmp_path / "evaluation.db"),
    )
    client = TestClient(app)
    project_response = client.post(
        "/projects",
        json={"name": "FastAPI evaluation", "repositories": []},
    )
    project_id = project_response.json()["id"]
    experiment = experiment_manifest()

    create_response = client.post(
        f"/projects/{project_id}/evaluations/experiments",
        json={"manifest": experiment.model_dump(mode="json")},
    )

    assert create_response.status_code == 201
    assert create_response.json()["manifest"]["id"] == experiment.id
    assert create_response.json()["run_count"] == 0

    runs = completed_runs(experiment)
    for run in runs:
        response = client.put(
            f"/evaluations/experiments/{experiment.id}/runs/{run.manifest.id}",
            json=run.model_dump(mode="json"),
        )
        assert response.status_code == 200

    run_page = client.get(
        f"/evaluations/experiments/{experiment.id}/runs",
        params={"condition_id": "G-R", "status": "completed", "limit": 1},
    )

    assert run_page.status_code == 200
    assert run_page.json()["total"] == 1
    assert run_page.json()["items"][0]["run"]["scorecard"]["stage_results"][0][
        "quality_metrics"
    ][0]["numerator"] == 6

    report = compare_ablation_runs(
        experiment=experiment,
        runs=runs,
        ablation_condition_id="G-R",
        selectors=[selector()],
    )
    comparison_response = client.put(
        f"/evaluations/experiments/{experiment.id}/comparisons/G-R",
        json=report.model_dump(mode="json"),
    )

    assert comparison_response.status_code == 200
    assert comparison_response.json()["report"]["intervals"][0][
        "mean_delta"
    ] == pytest.approx(0.3)

    experiment_page = client.get(
        f"/projects/{project_id}/evaluations/experiments",
        params={"limit": 10, "offset": 0},
    )
    comparison_page = client.get(
        f"/evaluations/experiments/{experiment.id}/comparisons"
    )

    assert experiment_page.status_code == 200
    assert experiment_page.json()["items"][0]["completed_run_count"] == 2
    assert experiment_page.json()["items"][0]["comparison_count"] == 1
    assert comparison_page.json()["total"] == 1

    changed = runs[0].model_copy(update={"latency_ms": 99})
    immutable_response = client.put(
        f"/evaluations/experiments/{experiment.id}/runs/{changed.manifest.id}",
        json=changed.model_dump(mode="json"),
    )
    assert immutable_response.status_code == 409
    assert "immutable" in immutable_response.json()["detail"]


def test_evaluation_api_rejects_unknown_project(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "GUIDESYNC_DATABASE_URL",
        sqlite_database_url(tmp_path / "missing-project.db"),
    )
    response = TestClient(app).post(
        "/projects/missing/evaluations/experiments",
        json={"manifest": experiment_manifest().model_dump(mode="json")},
    )

    assert response.status_code == 404


def test_completed_offline_evaluation_can_omit_latency() -> None:
    experiment = experiment_manifest()
    run = completed_runs(experiment)[0].model_copy(update={"latency_ms": None})

    assert run.status == EvaluationRunStatus.COMPLETED
    assert run.latency_ms is None


def test_failed_evaluation_can_retain_a_partial_scorecard() -> None:
    experiment = experiment_manifest()
    completed = completed_runs(experiment)[0]

    failed = EvaluationExperimentRun(
        manifest=completed.manifest,
        status=EvaluationRunStatus.FAILED,
        scorecard=completed.scorecard,
        failure="terminated",
        latency_ms=636_296,
    )

    assert failed.scorecard is not None
    assert failed.failure == "terminated"


def experiment_manifest():
    conditions = [
        protocol
        for protocol in default_condition_protocols(include_baselines=False)
        if protocol.condition.id in {"G", "G-R"}
    ]
    return build_experiment_manifest(
        cases=[
            EvaluationCaseManifest(
                id="fastapi-case-1",
                repository_url="https://github.com/fastapi/fastapi",
                base_commit="base-commit",
                head_commit="head-commit",
                allowed_paths=["fastapi", "tests", "docs"],
                withheld_paths=["docs/en/docs/release-notes.md"],
                input_checksums={"diff.patch": digest("diff")},
                input_artifact_refs={"diff.patch": "artifact:fastapi-case-1:diff"},
                index_commit="base-commit",
                gold_version="gold-v1",
                gold_checksum=digest("gold"),
                gold_artifact_ref="artifact:fastapi-case-1:gold",
            )
        ],
        conditions=conditions,
        configuration=FrozenEvaluationConfiguration(
            application_commit="guidesync-commit",
            prompt_checksums={"documentation": digest("prompt")},
            prompt_artifact_refs={"documentation": "repo:prompt"},
            model_role_configuration_checksum=digest("model"),
            model_role_configuration_artifact_ref="artifact:model",
            evaluator_version="evaluation-v1",
            runner_version="runner-v1",
        ),
        bootstrap_iterations=100,
    )


def completed_runs(experiment) -> list[EvaluationExperimentRun]:
    protocols = {
        protocol.condition.id: protocol for protocol in experiment.conditions
    }
    values = {"G": 9, "G-R": 6}
    return [
        EvaluationExperimentRun(
            manifest=manifest,
            status=EvaluationRunStatus.COMPLETED,
            latency_ms=25,
            artifact_refs=[f"artifact:{manifest.id}"],
            transcript_refs=[f"transcript:{manifest.id}"],
            scorecard=PipelineEvaluationScorecard(
                case_id=manifest.case_id,
                gold_version="gold-v1",
                evaluator_version="evaluation-v1",
                condition=protocols[manifest.condition_id].condition,
                stage_results=[
                    StageEvaluationResult(
                        case_id=manifest.case_id,
                        condition_id=manifest.condition_id,
                        stage=PipelineStage.END_TO_END,
                        status=EvaluationMeasurementStatus.MEASURED,
                        run_id=manifest.id,
                        quality_metrics=[
                            ratio_metric(
                                "strict_completeness",
                                values[manifest.condition_id],
                                10,
                            )
                        ],
                        artifact_refs=[f"artifact:{manifest.id}:score"],
                    )
                ],
            ),
        )
        for manifest in build_run_manifests(experiment)
    ]


def selector() -> EvaluationMetricSelector:
    return EvaluationMetricSelector(
        stage=PipelineStage.END_TO_END,
        group=EvaluationMetricGroup.QUALITY,
        metric_name="strict_completeness",
    )


def digest(value: str) -> str:
    return (value.encode().hex() + ("0" * 64))[:64]
