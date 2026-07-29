from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter

from guidesync_agent.schemas import (
    EvaluationCaseManifest,
    EvaluationConditionKind,
    EvaluationConditionProtocol,
    EvaluationExecutionFailure,
    EvaluationExecutionResult,
    EvaluationExperimentManifest,
    EvaluationExperimentRun,
    EvaluationRunManifest,
    EvaluationRunStatus,
    FrozenEvaluationConfiguration,
    PipelineEvaluationScorecard,
)
from guidesync_agent.services.evaluation_conditions import (
    default_condition_protocols,
)
from guidesync_agent.services.evaluation_manifest_utils import (
    condition_protocol_checksum,
    experiment_checksum,
    model_checksum,
    safe_id,
    stable_seed,
)

EvaluationExecutor = Callable[
    [EvaluationRunManifest],
    Awaitable[EvaluationExecutionResult | EvaluationExecutionFailure],
]


def build_experiment_manifest(
    *,
    cases: list[EvaluationCaseManifest],
    configuration: FrozenEvaluationConfiguration,
    conditions: list[EvaluationConditionProtocol] | None = None,
    repetitions: int = 1,
    bootstrap_iterations: int = 2000,
    confidence_level: float = 0.95,
    random_seed: int = 1729,
) -> EvaluationExperimentManifest:
    manifest = EvaluationExperimentManifest(
        id="pending",
        cases=cases,
        conditions=conditions or default_condition_protocols(),
        configuration=configuration,
        repetitions=repetitions,
        bootstrap_iterations=bootstrap_iterations,
        confidence_level=confidence_level,
        random_seed=random_seed,
    )
    return manifest.model_copy(
        update={"id": f"experiment-{experiment_checksum(manifest)[:16]}"}
    )


def build_run_manifests(
    experiment: EvaluationExperimentManifest,
) -> list[EvaluationRunManifest]:
    validate_experiment_integrity(experiment)
    experiment_digest = experiment_checksum(experiment)
    configuration_digest = model_checksum(experiment.configuration)
    manifests: list[EvaluationRunManifest] = []
    for case in experiment.cases:
        for protocol in experiment.conditions:
            if protocol.bounded_case_ids and case.id not in protocol.bounded_case_ids:
                continue
            for repetition in range(1, experiment.repetitions + 1):
                run_id = (
                    f"{experiment.id}-{safe_id(case.id)}-"
                    f"{safe_id(protocol.condition.id)}-r{repetition}"
                )
                manifests.append(
                    EvaluationRunManifest(
                        id=run_id,
                        experiment_id=experiment.id,
                        case_id=case.id,
                        condition_id=protocol.condition.id,
                        repetition=repetition,
                        case_checksum=model_checksum(case),
                        condition_checksum=model_checksum(protocol),
                        configuration_checksum=configuration_digest,
                        experiment_checksum=experiment_digest,
                        random_seed=stable_seed(
                            experiment.random_seed,
                            case.id,
                            protocol.condition.id,
                            str(repetition),
                        ),
                    )
                )
    return manifests


async def execute_experiment(
    experiment: EvaluationExperimentManifest,
    executor: EvaluationExecutor,
) -> list[EvaluationExperimentRun]:
    cases = {case.id: case for case in experiment.cases}
    conditions = {
        protocol.condition.id: protocol for protocol in experiment.conditions
    }
    runs: list[EvaluationExperimentRun] = []
    for manifest in build_run_manifests(experiment):
        started = perf_counter()
        try:
            result = await executor(manifest)
            if isinstance(result, EvaluationExecutionFailure):
                runs.append(
                    EvaluationExperimentRun(
                        manifest=manifest,
                        status=EvaluationRunStatus.FAILED,
                        latency_ms=elapsed_ms(started),
                        transcript_refs=result.transcript_refs,
                        artifact_refs=result.artifact_refs,
                        usage=result.usage,
                        failure=result.failure,
                    )
                )
                continue
            validate_execution_result(
                result,
                manifest,
                cases[manifest.case_id],
                conditions[manifest.condition_id],
                experiment.configuration,
            )
            runs.append(
                EvaluationExperimentRun(
                    manifest=manifest,
                    status=EvaluationRunStatus.COMPLETED,
                    scorecard=result.scorecard,
                    latency_ms=elapsed_ms(started),
                    transcript_refs=result.transcript_refs,
                    artifact_refs=result.artifact_refs,
                    usage=result.usage,
                )
            )
        except Exception as exc:
            runs.append(
                EvaluationExperimentRun(
                    manifest=manifest,
                    status=EvaluationRunStatus.FAILED,
                    latency_ms=elapsed_ms(started),
                    failure=f"{type(exc).__name__}: {exc}",
                )
            )
    return runs


def validate_experiment_integrity(experiment: EvaluationExperimentManifest) -> None:
    expected_id = f"experiment-{experiment_checksum(experiment)[:16]}"
    if experiment.id != expected_id:
        raise ValueError(
            f"experiment id/checksum mismatch: expected {expected_id}, got {experiment.id}"
        )
    for protocol in experiment.conditions:
        expected = condition_protocol_checksum(protocol)
        if protocol.condition.config_checksum != expected:
            raise ValueError(f"{protocol.condition.id} condition checksum mismatch")


def validate_execution_result(
    result: EvaluationExecutionResult,
    manifest: EvaluationRunManifest,
    case: EvaluationCaseManifest,
    protocol: EvaluationConditionProtocol,
    configuration: FrozenEvaluationConfiguration,
) -> None:
    if result.applied_condition_checksum != manifest.condition_checksum:
        raise ValueError("executor did not attest the frozen condition checksum")
    validate_scorecard_identity(
        result.scorecard,
        manifest,
        case,
        protocol,
        configuration,
    )


def validate_scorecard_identity(
    scorecard: PipelineEvaluationScorecard,
    manifest: EvaluationRunManifest,
    case: EvaluationCaseManifest,
    protocol: EvaluationConditionProtocol,
    configuration: FrozenEvaluationConfiguration,
) -> None:
    if scorecard.case_id != manifest.case_id:
        raise ValueError("scorecard case does not match the run manifest")
    if scorecard.gold_version != case.gold_version:
        raise ValueError("scorecard gold version does not match the frozen case")
    if scorecard.evaluator_version != configuration.evaluator_version:
        raise ValueError("scorecard evaluator version does not match the experiment")
    if scorecard.condition != protocol.condition:
        raise ValueError("scorecard condition does not match the run manifest")


def full_condition(
    experiment: EvaluationExperimentManifest,
) -> EvaluationConditionProtocol:
    return next(
        protocol
        for protocol in experiment.conditions
        if protocol.condition.kind == EvaluationConditionKind.FULL
    )


def elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
