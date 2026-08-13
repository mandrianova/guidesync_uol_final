from __future__ import annotations

import pytest
from pydantic import ValidationError

from guidesync_agent.schemas import (
    BinaryClassificationCounts,
    EvaluationCondition,
    EvaluationConditionKind,
    EvaluationMeasurementStatus,
    PipelineStage,
)
from guidesync_agent.services.evaluation.metrics import (
    accuracy_metric,
    f_beta_metric,
    failed_metric,
    jaccard_stability_metric,
    ndcg_at_k_metric,
    paired_ablation_delta,
    precision_metric,
    ratio_metric,
    recall_at_k_metric,
    recall_metric,
    reciprocal_rank_metric,
    unique_document_ratio_at_k_metric,
    unique_documents_at_k_metric,
)


def test_binary_metrics_keep_counts_and_derived_rates() -> None:
    counts = BinaryClassificationCounts(
        true_positive=3,
        false_positive=1,
        false_negative=2,
        true_negative=4,
    )

    precision = precision_metric(counts)
    recall = recall_metric(counts)
    accuracy = accuracy_metric(counts)
    f1 = f_beta_metric(counts)

    assert (precision.numerator, precision.denominator, precision.value) == (3, 4, 0.75)
    assert recall.value == pytest.approx(0.6)
    assert accuracy.value == pytest.approx(0.7)
    assert f1.value == pytest.approx(2 / 3)
    assert all(
        metric.status == EvaluationMeasurementStatus.MEASURED
        for metric in (precision, recall, accuracy, f1)
    )


def test_empty_classification_denominators_are_undefined_not_zero() -> None:
    counts = BinaryClassificationCounts()

    for metric in (
        precision_metric(counts),
        recall_metric(counts),
        accuracy_metric(counts),
        f_beta_metric(counts),
    ):
        assert metric.status == EvaluationMeasurementStatus.UNDEFINED
        assert metric.value is None
        assert metric.denominator == 0


def test_ranked_metrics_deduplicate_paths_before_relevance_scoring() -> None:
    ranked = ["docs/other.md", "docs/a.md", "docs/a.md", "docs/b.md"]

    recall = recall_at_k_metric({"docs/a.md", "docs/b.md"}, ranked, k=3)
    reciprocal_rank = reciprocal_rank_metric({"docs/a.md", "docs/b.md"}, ranked)
    diversity = unique_document_ratio_at_k_metric(ranked, k=3)
    unique_documents = unique_documents_at_k_metric(ranked, k=3)

    assert recall.value == 1.0
    assert recall.numerator == 2
    assert reciprocal_rank.value == 0.5
    assert diversity.value == pytest.approx(2 / 3)
    assert unique_documents.value == 2
    assert unique_documents.unit == "documents"


def test_ndcg_uses_graded_relevance_and_stable_path_deduplication() -> None:
    relevance = {"docs/a.md": 3.0, "docs/b.md": 2.0, "docs/c.md": 1.0}

    perfect = ndcg_at_k_metric(relevance, ["docs/a.md", "docs/b.md", "docs/c.md"], k=3)
    partial = ndcg_at_k_metric(
        relevance,
        ["docs/b.md", "docs/b.md", "docs/c.md", "docs/a.md"],
        k=2,
    )

    assert perfect.value == 1.0
    assert partial.value is not None
    assert 0 < partial.value < 1


def test_empty_gold_sets_are_explicitly_undefined() -> None:
    assert recall_at_k_metric(set(), ["docs/a.md"], k=1).status == (
        EvaluationMeasurementStatus.UNDEFINED
    )
    assert reciprocal_rank_metric(set(), ["docs/a.md"]).status == (
        EvaluationMeasurementStatus.UNDEFINED
    )
    assert ndcg_at_k_metric({}, ["docs/a.md"], k=1).status == (
        EvaluationMeasurementStatus.UNDEFINED
    )
    assert jaccard_stability_metric(set(), set()).status == (
        EvaluationMeasurementStatus.UNDEFINED
    )
    assert unique_document_ratio_at_k_metric([], k=5).status == (
        EvaluationMeasurementStatus.UNDEFINED
    )
    assert unique_documents_at_k_metric([], k=5).value == 0


def test_jaccard_and_paired_delta_preserve_measured_zero_values() -> None:
    stability = jaccard_stability_metric({"a", "b"}, {"b", "c"})
    full = ratio_metric("obligation_recall", 0, 4)
    ablation = ratio_metric("obligation_recall", 0, 4)

    comparison = paired_ablation_delta(
        case_id="fastapi-pr-15022",
        stage=PipelineStage.PROJECT_PROFILE,
        metric_name="obligation_recall",
        full_condition_id="G",
        ablation_condition_id="G-P",
        full_metric=full,
        ablation_metric=ablation,
    )

    assert stability.value == pytest.approx(1 / 3)
    assert comparison.status == EvaluationMeasurementStatus.MEASURED
    assert comparison.full_value == 0
    assert comparison.ablation_value == 0
    assert comparison.delta == 0


def test_paired_delta_propagates_failed_measurements_without_numeric_values() -> None:
    comparison = paired_ablation_delta(
        case_id="fastapi-pr-15022",
        stage=PipelineStage.CHANGE_ANALYSIS,
        metric_name="obligation_recall",
        full_condition_id="G",
        ablation_condition_id="G-C",
        full_metric=failed_metric("obligation_recall", "local model timeout"),
        ablation_metric=ratio_metric("obligation_recall", 1, 2),
    )

    assert comparison.status == EvaluationMeasurementStatus.FAILED
    assert comparison.full_value is None
    assert comparison.ablation_value is None
    assert comparison.delta is None
    assert comparison.warnings == ["local model timeout"]


def test_invalid_metric_inputs_and_ablation_contracts_are_rejected() -> None:
    with pytest.raises(ValidationError):
        BinaryClassificationCounts(true_positive=-1)
    with pytest.raises(ValueError, match="beta"):
        f_beta_metric(BinaryClassificationCounts(true_positive=1), beta=0)
    with pytest.raises(ValueError, match="k"):
        recall_at_k_metric({"a"}, ["a"], k=0)
    with pytest.raises(ValueError, match="relevance"):
        ndcg_at_k_metric({"a": -1}, ["a"], k=1)
    with pytest.raises(ValidationError, match="removed_stage"):
        EvaluationCondition(
            id="G-P",
            kind=EvaluationConditionKind.ABLATION,
            label="No project profile",
            replacement="Project settings only",
        )
