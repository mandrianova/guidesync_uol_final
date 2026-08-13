from __future__ import annotations

import pytest
from pydantic import ValidationError

from guidesync_agent.schemas import (
    ChangeImpactClaimKind,
    ChangeImpactClaimSupport,
    ChangeImpactEvaluationInput,
    ChangeImpactFileAnalysis,
    ChangeImpactGoldCase,
    ChangeImpactGoldFile,
    ChangeImpactGoldObligation,
    ChangeImpactPredictedClaim,
    DocumentationObligationSeverity,
    EvaluationAdjudicationStatus,
    EvaluationMeasurementStatus,
    EvaluationMetric,
)
from guidesync_agent.services.evaluation.change_impact import evaluate_change_impact


def test_change_impact_evaluation_separates_quality_from_completion() -> None:
    evaluation_input = ChangeImpactEvaluationInput(
        gold=ChangeImpactGoldCase(
            case_id="fastapi-pr-15022",
            gold_version="v1",
            files=[
                ChangeImpactGoldFile(
                    path="fastapi/routing.py",
                    documentation_relevant=True,
                    obligations=[
                        obligation(
                            "stream-bytes",
                            DocumentationObligationSeverity.CRITICAL,
                        ),
                        obligation(
                            "stream-jsonl",
                            DocumentationObligationSeverity.MAJOR,
                        ),
                    ],
                ),
                ChangeImpactGoldFile(
                    path="tests/test_internal.py",
                    documentation_relevant=False,
                ),
                ChangeImpactGoldFile(
                    path="fastapi/responses.py",
                    documentation_relevant=True,
                    obligations=[
                        obligation(
                            "document-content-type",
                            DocumentationObligationSeverity.CRITICAL,
                        )
                    ],
                ),
            ],
        ),
        analyses=[
            ChangeImpactFileAnalysis(
                path="fastapi/routing.py",
                status=EvaluationMeasurementStatus.MEASURED,
                predicted_documentation_relevant=True,
                claims=[
                    predicted_claim(
                        "claim-stream-bytes",
                        DocumentationObligationSeverity.CRITICAL,
                        ["stream-bytes"],
                        ["diff:fastapi/routing.py"],
                    ),
                    predicted_claim(
                        "claim-stream-bytes-duplicate",
                        DocumentationObligationSeverity.CRITICAL,
                        ["stream-bytes"],
                        ["diff:fastapi/routing.py"],
                    ),
                    predicted_claim(
                        "claim-unsupported",
                        DocumentationObligationSeverity.MAJOR,
                        ["unknown-obligation"],
                        ["diff:unknown.py"],
                        support=ChangeImpactClaimSupport.NOT_ENOUGH_EVIDENCE,
                    ),
                ],
            ),
            ChangeImpactFileAnalysis(
                path="tests/test_internal.py",
                status=EvaluationMeasurementStatus.MEASURED,
                predicted_documentation_relevant=True,
            ),
            ChangeImpactFileAnalysis(
                path="fastapi/responses.py",
                status=EvaluationMeasurementStatus.FAILED,
                failure_reason="model timeout",
            ),
        ],
        available_evidence_refs=["diff:fastapi/routing.py"],
    )

    report = evaluate_change_impact(evaluation_input)

    assert metric(report.metrics, "analysis_completion_coverage").value == pytest.approx(2 / 3)
    assert metric(report.metrics, "analysis_failure_rate").value == pytest.approx(1 / 3)
    assert report.relevance_counts.model_dump() == {
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 0,
        "true_negative": 0,
    }
    assert metric(report.metrics, "relevance_precision").value == pytest.approx(0.5)
    assert metric(report.metrics, "relevance_recall").value == pytest.approx(1.0)
    assert metric(report.metrics, "obligation_precision").value == pytest.approx(1 / 3)
    assert metric(report.metrics, "obligation_recall").value == pytest.approx(0.5)
    assert metric(report.metrics, "obligation_f1").value == pytest.approx(0.4)
    assert metric(
        report.metrics,
        "severity_weighted_obligation_recall",
    ).value == pytest.approx(0.6)
    assert metric(report.metrics, "evaluable_obligation_coverage").value == pytest.approx(
        2 / 3
    )
    assert metric(report.metrics, "claim_valid_evidence_coverage").value == pytest.approx(
        2 / 3
    )
    assert metric(report.metrics, "evidence_ref_validity").value == pytest.approx(0.5)

    severity = {result.severity: result for result in report.obligation_by_severity}
    critical = severity[DocumentationObligationSeverity.CRITICAL]
    major = severity[DocumentationObligationSeverity.MAJOR]
    assert metric(critical.metrics, "critical_precision").value == pytest.approx(0.5)
    assert metric(critical.metrics, "critical_recall").value == pytest.approx(1.0)
    assert metric(major.metrics, "major_precision").value == pytest.approx(0.0)
    assert metric(major.metrics, "major_recall").value == pytest.approx(0.0)

    assert report.unsupported_claim_ids == ["claim-unsupported"]
    assert report.unmatched_claim_ids == ["claim-unsupported"]
    assert report.duplicate_claim_ids == ["claim-stream-bytes-duplicate"]
    assert report.missed_critical_obligation_ids == []
    assert report.unevaluated_gold_obligation_ids == ["document-content-type"]
    assert report.invalid_evidence_refs == ["diff:unknown.py"]
    assert report.invalid_gold_obligation_refs == [
        "claim-unsupported:unknown-obligation"
    ]
    assert report.failed_files == ["fastapi/responses.py"]
    assert report.unevaluated_files == []


def test_failed_analysis_cannot_be_misreported_as_a_quality_prediction() -> None:
    with pytest.raises(ValidationError):
        ChangeImpactFileAnalysis(
            path="fastapi/routing.py",
            status=EvaluationMeasurementStatus.FAILED,
            predicted_documentation_relevant=True,
        )


def test_single_annotator_obligations_are_scored_as_provisional() -> None:
    report = evaluate_change_impact(
        ChangeImpactEvaluationInput(
            gold=ChangeImpactGoldCase(
                case_id="case-1",
                gold_version="single-v1",
                files=[
                    ChangeImpactGoldFile(
                        path="src/stream.py",
                        documentation_relevant=True,
                        obligations=[
                            obligation(
                                "streaming",
                                DocumentationObligationSeverity.CRITICAL,
                                EvaluationAdjudicationStatus.SINGLE_ANNOTATOR,
                            )
                        ],
                    )
                ],
            ),
            analyses=[
                ChangeImpactFileAnalysis(
                    path="src/stream.py",
                    status=EvaluationMeasurementStatus.MEASURED,
                    predicted_documentation_relevant=True,
                    claims=[
                        predicted_claim(
                            "claim-streaming",
                            DocumentationObligationSeverity.CRITICAL,
                            ["streaming"],
                            ["diff:src/stream.py"],
                        )
                    ],
                )
            ],
            available_evidence_refs=["diff:src/stream.py"],
        )
    )

    assert metric(report.metrics, "adjudicated_gold_coverage").value == 0.0
    assert metric(report.metrics, "scorable_gold_coverage").value == 1.0
    assert metric(report.metrics, "obligation_recall").value == 1.0
    assert report.findings == [
        "1 gold obligations use single-annotator gold and were scored provisionally"
    ]


def obligation(
    obligation_id: str,
    severity: DocumentationObligationSeverity,
    status: EvaluationAdjudicationStatus = EvaluationAdjudicationStatus.ADJUDICATED,
) -> ChangeImpactGoldObligation:
    return ChangeImpactGoldObligation(
        id=obligation_id,
        kind=ChangeImpactClaimKind.OBLIGATION,
        statement=obligation_id,
        severity=severity,
        evidence_refs=[f"gold:{obligation_id}"],
        adjudication_status=status,
    )


def predicted_claim(
    claim_id: str,
    severity: DocumentationObligationSeverity,
    matched_ids: list[str],
    evidence_refs: list[str],
    support: ChangeImpactClaimSupport = ChangeImpactClaimSupport.SUPPORTED,
) -> ChangeImpactPredictedClaim:
    return ChangeImpactPredictedClaim(
        id=claim_id,
        kind=ChangeImpactClaimKind.OBLIGATION,
        statement=claim_id,
        severity=severity,
        support=support,
        matched_gold_obligation_ids=matched_ids,
        evidence_refs=evidence_refs,
    )


def metric(metrics: list[EvaluationMetric], name: str) -> EvaluationMetric:
    return next(item for item in metrics if item.name == name)
