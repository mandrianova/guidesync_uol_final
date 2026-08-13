from __future__ import annotations

import pytest

from guidesync_agent.schemas import (
    ChangeImpactClaimKind,
    ChangeImpactGoldObligation,
    ContentPreservationCheck,
    DocumentationGenerationEvaluationInput,
    DocumentationObligationSeverity,
    DocumentationPlanningEvaluationInput,
    DocumentationTargetAction,
    DocumentationTargetGold,
    DocumentationTargetPrediction,
    EvaluationAdjudicationStatus,
    EvaluationMeasurementStatus,
    EvaluationMetric,
    GeneratedAtomicClaim,
    GeneratedClaimRelevance,
    GeneratedClaimSupport,
    ReindexEvaluationInput,
    ReindexGoldDocument,
    ReindexObservedDocument,
    StructuralValidationCheck,
    ValidationEvaluationInput,
    ValidationFindingJudgment,
    ValidationGoldDefect,
)
from guidesync_agent.services.evaluation.documentation_output import (
    evaluate_documentation_generation,
    evaluate_documentation_planning,
)
from guidesync_agent.services.evaluation.validation_reindex import (
    evaluate_reindex,
    evaluate_validation,
)


def test_planning_evaluation_scores_targets_evidence_and_execution_separately() -> None:
    report = evaluate_documentation_planning(
        DocumentationPlanningEvaluationInput(
            case_id="case-1",
            gold_targets=[
                DocumentationTargetGold(
                    id="target-guide",
                    path="docs/guide.md",
                    action=DocumentationTargetAction.UPDATE,
                    section="Configuration",
                ),
                DocumentationTargetGold(
                    id="target-new",
                    path="docs/new.md",
                    action=DocumentationTargetAction.CREATE,
                ),
            ],
            planned_targets=[
                target(
                    "plan-guide",
                    "docs/guide.md",
                    DocumentationTargetAction.UPDATE,
                    "configuration",
                    ["evidence:guide"],
                ),
                target(
                    "plan-extra",
                    "docs/extra.md",
                    DocumentationTargetAction.UPDATE,
                ),
                target(
                    "plan-new",
                    "docs/new.md",
                    DocumentationTargetAction.UPDATE,
                ),
            ],
            executed_targets=[
                target(
                    "edit-guide",
                    "docs/guide.md",
                    DocumentationTargetAction.UPDATE,
                    "Configuration",
                ),
                target(
                    "edit-surprise",
                    "docs/surprise.md",
                    DocumentationTargetAction.CREATE,
                ),
            ],
            available_evidence_refs=["evidence:guide"],
        )
    )

    assert metric(report.metrics, "target_document_precision").value == pytest.approx(2 / 3)
    assert metric(report.metrics, "target_document_recall").value == pytest.approx(1.0)
    assert metric(report.metrics, "create_update_accuracy").value == pytest.approx(0.5)
    assert metric(report.metrics, "target_section_accuracy").value == pytest.approx(1.0)
    assert metric(report.metrics, "plan_evidence_coverage").value == pytest.approx(1 / 3)
    assert metric(report.metrics, "plan_execution_precision").value == pytest.approx(0.5)
    assert metric(report.metrics, "plan_execution_recall").value == pytest.approx(1 / 3)
    assert metric(report.metrics, "plan_execution_jaccard").value == pytest.approx(0.25)
    assert report.unnecessary_plan_ids == ["plan-extra"]
    assert report.wrong_action_plan_ids == ["plan-new"]
    assert report.planned_not_executed_ids == ["plan-extra", "plan-new"]
    assert report.unplanned_executed_ids == ["edit-surprise"]


def test_generation_evaluation_uses_atomic_claims_and_preserves_edit_diagnostics() -> None:
    report = evaluate_documentation_generation(
        DocumentationGenerationEvaluationInput(
            case_id="case-1",
            status=EvaluationMeasurementStatus.MEASURED,
            gold_obligations=[
                obligation("o-critical", DocumentationObligationSeverity.CRITICAL),
                obligation("o-major", DocumentationObligationSeverity.MAJOR),
            ],
            claims=[
                claim(
                    "claim-supported",
                    GeneratedClaimSupport.SUPPORTED,
                    GeneratedClaimRelevance.RELEVANT,
                    ["o-critical"],
                    ["evidence:diff"],
                ),
                claim(
                    "claim-duplicate",
                    GeneratedClaimSupport.SUPPORTED,
                    GeneratedClaimRelevance.RELEVANT,
                    ["o-critical"],
                    ["evidence:diff"],
                ),
                claim(
                    "claim-unknown",
                    GeneratedClaimSupport.NOT_ENOUGH_EVIDENCE,
                    GeneratedClaimRelevance.RELEVANT,
                    [],
                    ["evidence:unknown"],
                ),
                claim(
                    "claim-irrelevant",
                    GeneratedClaimSupport.SUPPORTED,
                    GeneratedClaimRelevance.IRRELEVANT,
                    ["o-major"],
                    [],
                ),
            ],
            available_evidence_refs=["evidence:diff"],
            planned_scope_ids=["docs/guide.md#one", "docs/guide.md#two"],
            changed_scope_ids=["docs/guide.md#one", "docs/guide.md#surprise"],
            preservation_checks=[
                ContentPreservationCheck(id="surrounding-1", before_hash="a", after_hash="a"),
                ContentPreservationCheck(id="surrounding-2", before_hash="b", after_hash="c"),
            ],
            structural_checks=[
                StructuralValidationCheck(id="markdown", passed=True),
                StructuralValidationCheck(id="links", passed=False),
            ],
            output_artifact_ref="artifact:pre-validation",
        )
    )

    assert metric(report.metrics, "atomic_claim_precision").value == pytest.approx(0.5)
    assert metric(report.metrics, "weighted_obligation_recall").value == pytest.approx(0.6)
    assert metric(report.metrics, "output_f1").value == pytest.approx(6 / 11)
    assert metric(report.metrics, "output_f0.5").value == pytest.approx(15 / 29)
    assert metric(report.metrics, "claim_traceability").value == pytest.approx(0.5)
    assert metric(report.metrics, "edit_scope_precision").value == pytest.approx(0.5)
    assert metric(report.metrics, "planned_scope_coverage").value == pytest.approx(0.5)
    assert metric(
        report.metrics,
        "surrounding_content_preservation",
    ).value == pytest.approx(0.5)
    assert metric(
        report.metrics,
        "structural_validation_pass_rate",
    ).value == pytest.approx(0.5)
    assert report.missing_obligation_ids == ["o-major"]
    assert report.unsupported_claim_ids == ["claim-unknown"]
    assert report.irrelevant_claim_ids == ["claim-irrelevant"]
    assert report.duplicate_claim_ids == ["claim-duplicate"]
    assert report.invalid_evidence_refs == ["evidence:unknown"]
    assert report.unplanned_changed_scope_ids == ["docs/guide.md#surprise"]
    assert report.altered_surrounding_content_ids == ["surrounding-2"]
    assert report.failed_structural_check_ids == ["links"]
    assert report.output_artifact_ref == "artifact:pre-validation"


def test_visual_obligations_require_a_linked_gold_visual_fact() -> None:
    visual_obligation = obligation(
        "o-visual",
        DocumentationObligationSeverity.MAJOR,
    ).model_copy(update={"visual_fact_ids": ["fact-open"]})
    text_obligation = obligation("o-text", DocumentationObligationSeverity.MINOR)
    report = evaluate_documentation_generation(
        DocumentationGenerationEvaluationInput(
            case_id="case-ui",
            status=EvaluationMeasurementStatus.MEASURED,
            gold_obligations=[visual_obligation, text_obligation],
            claims=[
                GeneratedAtomicClaim(
                    id="claim-visual-ungrounded",
                    statement="The open state uses a close icon.",
                    support=GeneratedClaimSupport.SUPPORTED,
                    relevance=GeneratedClaimRelevance.RELEVANT,
                    matched_gold_obligation_ids=["o-visual"],
                    matched_visual_fact_ids=["fact-unknown"],
                ),
                GeneratedAtomicClaim(
                    id="claim-text",
                    statement="The existing menu behavior is unchanged.",
                    support=GeneratedClaimSupport.SUPPORTED,
                    relevance=GeneratedClaimRelevance.RELEVANT,
                    matched_gold_obligation_ids=["o-text"],
                ),
            ],
        )
    )

    assert metric(report.metrics, "weighted_obligation_recall").value == pytest.approx(
        1 / 3
    )
    assert metric(report.metrics, "visual_obligation_recall").value == 0
    assert report.missing_obligation_ids == ["o-visual"]
    assert report.invalid_visual_fact_ids == ["fact-unknown"]

    grounded = evaluate_documentation_generation(
        DocumentationGenerationEvaluationInput(
            case_id="case-ui",
            status=EvaluationMeasurementStatus.MEASURED,
            gold_obligations=[visual_obligation],
            claims=[
                GeneratedAtomicClaim(
                    id="claim-visual-grounded",
                    statement="The open state uses a close icon.",
                    support=GeneratedClaimSupport.SUPPORTED,
                    relevance=GeneratedClaimRelevance.RELEVANT,
                    matched_gold_obligation_ids=["o-visual"],
                    matched_visual_fact_ids=["fact-open"],
                )
            ],
        )
    )

    assert metric(grounded.metrics, "weighted_obligation_recall").value == 1
    assert metric(grounded.metrics, "visual_obligation_recall").value == 1


def test_validation_evaluation_compares_findings_to_pre_and_post_defects() -> None:
    report = evaluate_validation(
        ValidationEvaluationInput(
            case_id="case-1",
            status=EvaluationMeasurementStatus.MEASURED,
            gold_defects=[
                defect("d-critical", DocumentationObligationSeverity.CRITICAL),
                defect("d-major", DocumentationObligationSeverity.MAJOR),
            ],
            findings=[
                finding("finding-1", ["d-critical"], ["evidence:output"]),
                finding("finding-duplicate", ["d-critical"], ["evidence:output"]),
                finding("finding-false", ["unknown-defect"], ["evidence:unknown"]),
            ],
            corrected_gold_defect_ids=["d-critical"],
            residual_gold_defect_ids=["d-major"],
            available_evidence_refs=["evidence:output"],
            pre_validation_artifact_ref="artifact:pre",
            post_validation_artifact_ref="artifact:post",
        )
    )

    assert metric(report.metrics, "defect_detection_precision").value == pytest.approx(1 / 3)
    assert metric(report.metrics, "defect_detection_recall").value == pytest.approx(0.5)
    assert metric(report.metrics, "defect_detection_f1").value == pytest.approx(0.4)
    assert metric(report.metrics, "validator_false_positive_rate").value == pytest.approx(
        2 / 3
    )
    assert metric(report.metrics, "defect_correction_rate").value == pytest.approx(1.0)
    assert metric(report.metrics, "residual_defect_rate").value == pytest.approx(0.5)
    assert report.missed_defect_ids == ["d-major"]
    assert report.false_positive_finding_ids == ["finding-duplicate", "finding-false"]
    assert report.duplicate_finding_ids == ["finding-duplicate"]
    assert report.invalid_evidence_refs == ["evidence:unknown"]
    assert report.invalid_gold_defect_refs == ["finding-false:unknown-defect"]
    assert report.pre_validation_artifact_ref == "artifact:pre"
    assert report.post_validation_artifact_ref == "artifact:post"


def test_single_annotator_output_and_defects_are_scored_as_provisional() -> None:
    generation = evaluate_documentation_generation(
        DocumentationGenerationEvaluationInput(
            case_id="case-1",
            status=EvaluationMeasurementStatus.MEASURED,
            gold_obligations=[
                obligation(
                    "o-single",
                    DocumentationObligationSeverity.CRITICAL,
                    EvaluationAdjudicationStatus.SINGLE_ANNOTATOR,
                )
            ],
            claims=[
                claim(
                    "claim-single",
                    GeneratedClaimSupport.SUPPORTED,
                    GeneratedClaimRelevance.RELEVANT,
                    ["o-single"],
                    ["evidence:diff"],
                )
            ],
            available_evidence_refs=["evidence:diff"],
        )
    )
    validation = evaluate_validation(
        ValidationEvaluationInput(
            case_id="case-1",
            status=EvaluationMeasurementStatus.MEASURED,
            gold_defects=[
                defect(
                    "d-single",
                    DocumentationObligationSeverity.MAJOR,
                    EvaluationAdjudicationStatus.SINGLE_ANNOTATOR,
                )
            ],
            findings=[
                finding("finding-single", ["d-single"], ["evidence:output"])
            ],
            corrected_gold_defect_ids=["d-single"],
            available_evidence_refs=["evidence:output"],
        )
    )

    assert metric(generation.metrics, "weighted_obligation_recall").value == 1.0
    assert generation.findings == [
        "1 gold obligations use single-annotator gold and were scored provisionally"
    ]
    assert metric(validation.metrics, "defect_detection_recall").value == 1.0
    assert validation.findings == [
        "1 gold defects use single-annotator gold and were scored provisionally"
    ]


def test_reindex_evaluation_separates_coverage_from_freshness_quality() -> None:
    report = evaluate_reindex(
        ReindexEvaluationInput(
            case_id="case-1",
            status=EvaluationMeasurementStatus.MEASURED,
            gold_documents=[
                ReindexGoldDocument(
                    path="docs/guide.md",
                    expected_commit="commit-2",
                    expected_content_hash="hash-2",
                    expected_sections=["Configuration", "Limitations"],
                    expected_query_ids=["query-config", "query-limit"],
                ),
                ReindexGoldDocument(
                    path="docs/new.md",
                    expected_commit="commit-2",
                    expected_content_hash="hash-new",
                    expected_sections=["Overview"],
                    expected_query_ids=["query-new"],
                ),
            ],
            observed_documents=[
                ReindexObservedDocument(
                    path="docs/guide.md",
                    indexed_commit="commit-2",
                    indexed_content_hash="hash-1",
                    indexed_sections=["Configuration"],
                    successful_query_ids=["query-config"],
                ),
                ReindexObservedDocument(path="docs/unexpected.md"),
            ],
        )
    )

    assert metric(
        report.metrics,
        "changed_document_reindex_coverage",
    ).value == pytest.approx(0.5)
    assert metric(report.metrics, "indexed_commit_accuracy").value == pytest.approx(1.0)
    assert metric(report.metrics, "indexed_content_hash_accuracy").value == pytest.approx(
        0.0
    )
    assert metric(report.metrics, "reindexed_section_coverage").value == pytest.approx(0.5)
    assert metric(report.metrics, "section_evaluation_coverage").value == pytest.approx(
        2 / 3
    )
    assert metric(report.metrics, "post_edit_query_success").value == pytest.approx(0.5)
    assert metric(report.metrics, "query_evaluation_coverage").value == pytest.approx(
        2 / 3
    )
    assert report.missing_document_paths == ["docs/new.md"]
    assert report.unexpected_document_paths == ["docs/unexpected.md"]
    assert report.stale_content_paths == ["docs/guide.md"]
    assert report.missing_section_refs == [
        "docs/guide.md#Limitations",
        "docs/new.md#Overview",
    ]
    assert report.failed_query_ids == [
        "docs/guide.md:query-limit",
        "docs/new.md:query-new",
    ]


def target(
    target_id: str,
    path: str,
    action: DocumentationTargetAction,
    section: str | None = None,
    evidence_refs: list[str] | None = None,
) -> DocumentationTargetPrediction:
    return DocumentationTargetPrediction(
        id=target_id,
        path=path,
        action=action,
        section=section,
        evidence_refs=evidence_refs or [],
    )


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


def claim(
    claim_id: str,
    support: GeneratedClaimSupport,
    relevance: GeneratedClaimRelevance,
    matched_ids: list[str],
    evidence_refs: list[str],
) -> GeneratedAtomicClaim:
    return GeneratedAtomicClaim(
        id=claim_id,
        statement=claim_id,
        support=support,
        relevance=relevance,
        matched_gold_obligation_ids=matched_ids,
        evidence_refs=evidence_refs,
    )


def defect(
    defect_id: str,
    severity: DocumentationObligationSeverity,
    status: EvaluationAdjudicationStatus = EvaluationAdjudicationStatus.ADJUDICATED,
) -> ValidationGoldDefect:
    return ValidationGoldDefect(
        id=defect_id,
        severity=severity,
        evidence_refs=[f"gold:{defect_id}"],
        adjudication_status=status,
    )


def finding(
    finding_id: str,
    matched_ids: list[str],
    evidence_refs: list[str],
) -> ValidationFindingJudgment:
    return ValidationFindingJudgment(
        id=finding_id,
        matched_gold_defect_ids=matched_ids,
        evidence_refs=evidence_refs,
    )


def metric(metrics: list[EvaluationMetric], name: str) -> EvaluationMetric:
    return next(item for item in metrics if item.name == name)
