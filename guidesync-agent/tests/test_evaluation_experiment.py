from __future__ import annotations

import asyncio

import pytest

from guidesync_agent.schemas import (
    EvaluationCaseManifest,
    EvaluationConditionKind,
    EvaluationExecutionFailure,
    EvaluationExecutionResult,
    EvaluationExperimentManifest,
    EvaluationExperimentRun,
    EvaluationMeasurementStatus,
    EvaluationMetricGroup,
    EvaluationMetricSelector,
    EvaluationRunManifest,
    EvaluationRunStatus,
    FrozenEvaluationConfiguration,
    PipelineEvaluationScorecard,
    PipelineStage,
    StageEvaluationResult,
)
from guidesync_agent.services.evaluation_comparison import compare_ablation_runs
from guidesync_agent.services.evaluation_conditions import (
    default_condition_protocols,
)
from guidesync_agent.services.evaluation_experiment import (
    build_experiment_manifest,
    build_run_manifests,
    execute_experiment,
    validate_execution_result,
)
from guidesync_agent.services.evaluation_metrics import ratio_metric


def test_default_protocols_declare_bounded_ablation_replacements() -> None:
    protocols = default_condition_protocols()
    by_id = {protocol.condition.id: protocol for protocol in protocols}

    assert set(by_id) == {
        "G",
        "G-P",
        "G-A",
        "G-R",
        "G-C",
        "G-S",
        "G-SD",
        "G-L",
        "G-V",
        "G-X",
        "B0",
        "B1",
        "B2",
        "B3",
    }
    for condition_id in (
        "G-P",
        "G-A",
        "G-R",
        "G-C",
        "G-S",
        "G-SD",
        "G-L",
        "G-V",
        "G-X",
    ):
        protocol = by_id[condition_id]
        assert protocol.condition.kind == EvaluationConditionKind.ABLATION
        assert protocol.changed_stages == [protocol.condition.removed_stage]
        assert protocol.behavior == protocol.condition.replacement
        assert protocol.condition.config_checksum
    assert by_id["G"].changed_stages == []
    assert by_id["G"].ui_evidence_modality.value == "dom_aria_png"
    assert by_id["G-S"].ui_evidence_modality.value == "none"
    assert by_id["G-SD"].ui_evidence_modality.value == "dom_aria"
    assert all(by_id[baseline].changed_stages for baseline in ("B0", "B1", "B2", "B3"))


def test_run_manifests_are_deterministic_and_retain_repetitions() -> None:
    experiment = experiment_manifest(repetitions=2)

    first = build_run_manifests(experiment)
    second = build_run_manifests(experiment)

    assert first == second
    assert len(first) == 8
    assert {item.repetition for item in first} == {1, 2}
    assert all(item.experiment_checksum for item in first)
    assert all(item.configuration_checksum for item in first)
    assert len({item.random_seed for item in first}) == len(first)

    tampered = experiment.model_copy(
        update={
            "cases": [
                experiment.cases[0].model_copy(update={"head_commit": "tampered"}),
                experiment.cases[1],
            ]
        }
    )
    with pytest.raises(ValueError, match="experiment id/checksum mismatch"):
        build_run_manifests(tampered)


def test_executor_must_attest_the_condition_it_applied() -> None:
    experiment = experiment_manifest(repetitions=1)
    manifest = build_run_manifests(experiment)[0]
    protocol = next(
        item
        for item in experiment.conditions
        if item.condition.id == manifest.condition_id
    )
    result = EvaluationExecutionResult(
        applied_condition_checksum="wrong-condition",
        scorecard=PipelineEvaluationScorecard(
            case_id=manifest.case_id,
            gold_version="gold-v1",
            evaluator_version="evaluator-v1",
            condition=protocol.condition,
        ),
    )

    with pytest.raises(ValueError, match="attest"):
        validate_execution_result(
            result,
            manifest,
            next(case for case in experiment.cases if case.id == manifest.case_id),
            protocol,
            experiment.configuration,
        )


def test_runner_records_failures_and_comparison_uses_only_paired_scores() -> None:  # noqa: PLR0915
    experiment = experiment_manifest(repetitions=2)
    values = {
        ("case-a", "G", 1): 0.8,
        ("case-a", "G", 2): 0.9,
        ("case-a", "G-R", 1): 0.5,
        ("case-b", "G", 1): 0.7,
        ("case-b", "G", 2): 0.9,
        ("case-b", "G-R", 1): 0.6,
        ("case-b", "G-R", 2): 0.5,
    }
    protocols = {
        protocol.condition.id: protocol for protocol in experiment.conditions
    }

    async def executor(
        manifest: EvaluationRunManifest,
    ) -> EvaluationExecutionResult | EvaluationExecutionFailure:
        key = (manifest.case_id, manifest.condition_id, manifest.repetition)
        if key == ("case-a", "G-R", 2):
            return EvaluationExecutionFailure(
                failure="local model timeout",
                transcript_refs=[f"transcript:{manifest.id}"],
                artifact_refs=[f"partial-artifact:{manifest.id}"],
            )
        value = values[key]
        condition = protocols[manifest.condition_id].condition
        return EvaluationExecutionResult(
            applied_condition_checksum=manifest.condition_checksum,
            scorecard=PipelineEvaluationScorecard(
                case_id=manifest.case_id,
                gold_version="gold-v1",
                evaluator_version="evaluator-v1",
                condition=condition,
                stage_results=[
                    StageEvaluationResult(
                        case_id=manifest.case_id,
                        condition_id=condition.id,
                        stage=PipelineStage.END_TO_END,
                        status=EvaluationMeasurementStatus.MEASURED,
                        run_id=manifest.id,
                        quality_metrics=[
                            ratio_metric("strict_completeness", value, 1)
                        ],
                    )
                ],
            ),
            transcript_refs=[f"transcript:{manifest.id}"],
            artifact_refs=[f"artifact:{manifest.id}"],
        )

    runs = asyncio.run(execute_experiment(experiment, executor))

    assert len(runs) == 8
    failed = [run for run in runs if run.status.value == "failed"]
    assert len(failed) == 1
    assert failed[0].scorecard is None
    assert failed[0].failure == "local model timeout"
    assert failed[0].transcript_refs
    assert failed[0].artifact_refs
    assert all(
        run.transcript_refs and run.artifact_refs
        for run in runs
        if run.status.value == "completed"
    )

    selector = EvaluationMetricSelector(
        stage=PipelineStage.END_TO_END,
        group=EvaluationMetricGroup.QUALITY,
        metric_name="strict_completeness",
    )
    report = compare_ablation_runs(
        experiment=experiment,
        runs=runs,
        ablation_condition_id="G-R",
        selectors=[selector],
    )

    assert report.excluded_pair_ids == ["case-a:r2"]
    assert len(report.observations) == 3
    assert all(
        item.delta.status == EvaluationMeasurementStatus.MEASURED
        for item in report.observations
    )
    interval = report.intervals[0]
    assert interval.paired_count == 3
    assert interval.case_count == 2
    assert interval.mean_delta == pytest.approx((0.3 + ((0.1 + 0.4) / 2)) / 2)
    assert interval.lower_bound is not None
    assert interval.mean_delta is not None
    assert interval.upper_bound is not None
    assert interval.lower_bound <= interval.mean_delta <= interval.upper_bound
    assert any("local model timeout" in warning for warning in report.warnings)


def test_comparison_rejects_runs_with_different_frozen_case_checksums() -> None:
    experiment = experiment_manifest(repetitions=1)
    runs = completed_runs(experiment)
    ablation_index = next(
        index
        for index, run in enumerate(runs)
        if run.manifest.case_id == "case-a"
        and run.manifest.condition_id == "G-R"
    )
    runs[ablation_index] = runs[ablation_index].model_copy(
        update={
            "manifest": runs[ablation_index].manifest.model_copy(
                update={"case_checksum": "different"}
            )
        }
    )

    with pytest.raises(ValueError, match="frozen experiment manifest"):
        compare_ablation_runs(
            experiment=experiment,
            runs=runs,
            ablation_condition_id="G-R",
            selectors=[
                EvaluationMetricSelector(
                    stage=PipelineStage.END_TO_END,
                    group=EvaluationMetricGroup.QUALITY,
                    metric_name="strict_completeness",
                )
            ],
        )


def experiment_manifest(*, repetitions: int) -> EvaluationExperimentManifest:
    conditions = [
        protocol
        for protocol in default_condition_protocols(include_baselines=False)
        if protocol.condition.id in {"G", "G-R"}
    ]
    return build_experiment_manifest(
        cases=[case_manifest("case-a"), case_manifest("case-b")],
        configuration=FrozenEvaluationConfiguration(
            application_commit="guidesync-commit",
            prompt_checksums={"documentation": digest("prompt")},
            prompt_artifact_refs={
                "documentation": "repo:prompts/documentation.md"
            },
            model_role_configuration_checksum=digest("model-config"),
            model_role_configuration_artifact_ref="artifact:model-config",
            evaluator_version="evaluator-v1",
            runner_version="runner-v1",
        ),
        conditions=conditions,
        repetitions=repetitions,
        bootstrap_iterations=200,
        random_seed=42,
    )


def case_manifest(case_id: str) -> EvaluationCaseManifest:
    return EvaluationCaseManifest(
        id=case_id,
        repository_url="https://github.com/fastapi/fastapi",
        base_commit="base",
        head_commit="head",
        allowed_paths=["fastapi", "tests", "docs"],
        withheld_paths=["docs/release-notes.md"],
        input_checksums={"diff.patch": digest(f"{case_id}-diff")},
        input_artifact_refs={"diff.patch": f"artifact:{case_id}:diff"},
        index_commit="base",
        gold_version="gold-v1",
        gold_checksum=digest(f"{case_id}-gold"),
        gold_artifact_ref=f"artifact:{case_id}:gold",
    )


def completed_runs(
    experiment: EvaluationExperimentManifest,
) -> list[EvaluationExperimentRun]:
    protocols = {
        protocol.condition.id: protocol for protocol in experiment.conditions
    }
    runs: list[EvaluationExperimentRun] = []
    for manifest in build_run_manifests(experiment):
        condition = protocols[manifest.condition_id].condition
        runs.append(
            EvaluationExperimentRun(
                manifest=manifest,
                status=EvaluationRunStatus.COMPLETED,
                latency_ms=10,
                scorecard=PipelineEvaluationScorecard(
                    case_id=manifest.case_id,
                    gold_version="gold-v1",
                    evaluator_version="evaluator-v1",
                    condition=condition,
                    stage_results=[
                        StageEvaluationResult(
                            case_id=manifest.case_id,
                            condition_id=condition.id,
                            stage=PipelineStage.END_TO_END,
                            status=EvaluationMeasurementStatus.MEASURED,
                            quality_metrics=[
                                ratio_metric("strict_completeness", 0.8, 1)
                            ],
                        )
                    ],
                ),
            )
        )
    return runs


def digest(value: str) -> str:
    return (value.encode().hex() + ("0" * 64))[:64]
