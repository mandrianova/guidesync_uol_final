from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from math import log2

from guidesync_agent.schemas import (
    BinaryClassificationCounts,
    EvaluationMeasurementStatus,
    EvaluationMetric,
    PairedAblationDelta,
    PipelineStage,
)


def ratio_metric(
    name: str,
    numerator: float,
    denominator: float,
    *,
    unit: str = "ratio",
) -> EvaluationMetric:
    if numerator < 0:
        raise ValueError("metric numerator cannot be negative")
    if denominator < 0:
        raise ValueError("metric denominator cannot be negative")
    if denominator == 0:
        return EvaluationMetric(
            name=name,
            status=EvaluationMeasurementStatus.UNDEFINED,
            numerator=numerator,
            denominator=denominator,
            unit=unit,
            warnings=["metric denominator is zero"],
        )
    return EvaluationMetric(
        name=name,
        status=EvaluationMeasurementStatus.MEASURED,
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator,
        unit=unit,
    )


def not_evaluated_metric(name: str, reason: str) -> EvaluationMetric:
    return EvaluationMetric(
        name=name,
        status=EvaluationMeasurementStatus.NOT_EVALUATED,
        warnings=[reason],
    )


def failed_metric(name: str, reason: str) -> EvaluationMetric:
    return EvaluationMetric(
        name=name,
        status=EvaluationMeasurementStatus.FAILED,
        warnings=[reason],
    )


def precision_metric(counts: BinaryClassificationCounts) -> EvaluationMetric:
    return ratio_metric(
        "precision",
        counts.true_positive,
        counts.true_positive + counts.false_positive,
    )


def recall_metric(counts: BinaryClassificationCounts) -> EvaluationMetric:
    return ratio_metric(
        "recall",
        counts.true_positive,
        counts.true_positive + counts.false_negative,
    )


def accuracy_metric(counts: BinaryClassificationCounts) -> EvaluationMetric:
    correct = counts.true_positive + counts.true_negative
    total = correct + counts.false_positive + counts.false_negative
    return ratio_metric("accuracy", correct, total)


def f_beta_metric(
    counts: BinaryClassificationCounts,
    *,
    beta: float = 1.0,
) -> EvaluationMetric:
    if beta <= 0:
        raise ValueError("beta must be greater than zero")
    beta_squared = beta**2
    numerator = (1 + beta_squared) * counts.true_positive
    denominator = (
        numerator
        + beta_squared * counts.false_negative
        + counts.false_positive
    )
    return ratio_metric(f"f{beta:g}", numerator, denominator)


def f_beta_from_metrics(
    precision: EvaluationMetric,
    recall: EvaluationMetric,
    *,
    beta: float = 1.0,
    name: str | None = None,
) -> EvaluationMetric:
    if beta <= 0:
        raise ValueError("beta must be greater than zero")
    status = paired_measurement_status(precision.status, recall.status)
    metric_name = name or f"f{beta:g}"
    if status == EvaluationMeasurementStatus.FAILED:
        return failed_metric(metric_name, "precision or recall measurement failed")
    if status == EvaluationMeasurementStatus.NOT_EVALUATED:
        return not_evaluated_metric(metric_name, "precision or recall was not evaluated")
    if status == EvaluationMeasurementStatus.UNDEFINED:
        return EvaluationMetric(
            name=metric_name,
            status=EvaluationMeasurementStatus.UNDEFINED,
            warnings=["precision or recall is undefined"],
        )
    if precision.value is None or recall.value is None:
        raise ValueError("measured precision and recall must contain values")
    beta_squared = beta**2
    numerator = (1 + beta_squared) * precision.value * recall.value
    denominator = beta_squared * precision.value + recall.value
    return ratio_metric(metric_name, numerator, denominator)


def recall_at_k_metric(
    relevant_ids: Iterable[str],
    ranked_ids: Sequence[str],
    *,
    k: int,
) -> EvaluationMetric:
    validate_k(k)
    relevant = set(relevant_ids)
    if not relevant:
        return ratio_metric("recall_at_k", 0, 0)
    top_k = stable_unique(ranked_ids)[:k]
    return ratio_metric("recall_at_k", len(relevant.intersection(top_k)), len(relevant))


def reciprocal_rank_metric(
    relevant_ids: Iterable[str],
    ranked_ids: Sequence[str],
) -> EvaluationMetric:
    relevant = set(relevant_ids)
    if not relevant:
        return ratio_metric("reciprocal_rank", 0, 0)
    for rank, item_id in enumerate(stable_unique(ranked_ids), start=1):
        if item_id in relevant:
            return ratio_metric("reciprocal_rank", 1, rank)
    return ratio_metric("reciprocal_rank", 0, 1)


def ndcg_at_k_metric(
    relevance_by_id: Mapping[str, float],
    ranked_ids: Sequence[str],
    *,
    k: int,
) -> EvaluationMetric:
    validate_k(k)
    if any(relevance < 0 for relevance in relevance_by_id.values()):
        raise ValueError("relevance values cannot be negative")
    ideal_relevances = sorted(relevance_by_id.values(), reverse=True)[:k]
    ideal_dcg = discounted_cumulative_gain(ideal_relevances)
    if ideal_dcg == 0:
        return ratio_metric("ndcg_at_k", 0, 0)
    ranked_relevances = [
        relevance_by_id.get(item_id, 0.0)
        for item_id in stable_unique(ranked_ids)[:k]
    ]
    return ratio_metric(
        "ndcg_at_k",
        discounted_cumulative_gain(ranked_relevances),
        ideal_dcg,
    )


def unique_document_ratio_at_k_metric(
    ranked_document_paths: Sequence[str],
    *,
    k: int,
) -> EvaluationMetric:
    validate_k(k)
    top_k = ranked_document_paths[:k]
    return ratio_metric(
        "unique_document_ratio_at_k",
        len(set(top_k)),
        len(top_k),
    )


def unique_documents_at_k_metric(
    ranked_document_paths: Sequence[str],
    *,
    k: int,
) -> EvaluationMetric:
    validate_k(k)
    return ratio_metric(
        "unique_documents_at_k",
        len(set(ranked_document_paths[:k])),
        1,
        unit="documents",
    )


def jaccard_stability_metric(
    first_values: Iterable[str],
    second_values: Iterable[str],
) -> EvaluationMetric:
    first = set(first_values)
    second = set(second_values)
    union = first.union(second)
    if not union:
        return ratio_metric("jaccard_stability", 0, 0)
    return ratio_metric("jaccard_stability", len(first.intersection(second)), len(union))


def paired_ablation_delta(
    *,
    case_id: str,
    stage: PipelineStage,
    metric_name: str,
    full_condition_id: str,
    ablation_condition_id: str,
    full_metric: EvaluationMetric,
    ablation_metric: EvaluationMetric,
) -> PairedAblationDelta:
    status = paired_measurement_status(full_metric.status, ablation_metric.status)
    warnings = [*full_metric.warnings, *ablation_metric.warnings]
    if status != EvaluationMeasurementStatus.MEASURED:
        return PairedAblationDelta(
            case_id=case_id,
            stage=stage,
            metric_name=metric_name,
            full_condition_id=full_condition_id,
            ablation_condition_id=ablation_condition_id,
            status=status,
            warnings=warnings,
        )
    if full_metric.value is None or ablation_metric.value is None:
        raise ValueError("measured metrics must contain values")
    return PairedAblationDelta(
        case_id=case_id,
        stage=stage,
        metric_name=metric_name,
        full_condition_id=full_condition_id,
        ablation_condition_id=ablation_condition_id,
        status=EvaluationMeasurementStatus.MEASURED,
        full_value=full_metric.value,
        ablation_value=ablation_metric.value,
        delta=full_metric.value - ablation_metric.value,
        warnings=warnings,
    )


def stable_unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def validate_k(k: int) -> None:
    if k <= 0:
        raise ValueError("k must be greater than zero")


def discounted_cumulative_gain(relevances: Sequence[float]) -> float:
    return sum(
        (2**relevance - 1) / log2(rank + 1)
        for rank, relevance in enumerate(relevances, start=1)
    )


def paired_measurement_status(
    full_status: EvaluationMeasurementStatus,
    ablation_status: EvaluationMeasurementStatus,
) -> EvaluationMeasurementStatus:
    statuses = {full_status, ablation_status}
    for status in (
        EvaluationMeasurementStatus.FAILED,
        EvaluationMeasurementStatus.NOT_EVALUATED,
        EvaluationMeasurementStatus.UNDEFINED,
    ):
        if status in statuses:
            return status
    return EvaluationMeasurementStatus.MEASURED
