from __future__ import annotations

from collections.abc import Iterable

from guidesync_agent.schemas import (
    BinaryClassificationCounts,
    ChangeImpactEvaluationInput,
    ChangeImpactEvaluationReport,
    ChangeImpactFileAnalysis,
    ChangeImpactGoldFile,
    ChangeImpactGoldObligation,
    ChangeImpactPredictedClaim,
    DocumentationObligationSeverity,
    EvaluationAdjudicationStatus,
    EvaluationMeasurementStatus,
    EvaluationMetric,
)
from guidesync_agent.services.change_impact_assessment import (
    assess_claims,
    named_classification_metrics,
    severity_results,
)
from guidesync_agent.services.evaluation_adjudication import (
    gold_status_findings,
    is_scorable_gold,
)
from guidesync_agent.services.evaluation_metrics import (
    ratio_metric,
)

SEVERITY_WEIGHTS = {
    DocumentationObligationSeverity.CRITICAL: 3,
    DocumentationObligationSeverity.MAJOR: 2,
    DocumentationObligationSeverity.MINOR: 1,
}


def evaluate_change_impact(
    evaluation_input: ChangeImpactEvaluationInput,
) -> ChangeImpactEvaluationReport:
    gold_files = unique_gold_files(evaluation_input.gold.files)
    analyses = unique_analyses(evaluation_input.analyses)
    findings: list[str] = []
    unknown_analysis_paths = sorted(set(analyses).difference(gold_files))
    if unknown_analysis_paths:
        findings.append(
            f"{len(unknown_analysis_paths)} analyses do not match a frozen changed file"
        )

    known_analyses = {
        path: analysis for path, analysis in analyses.items() if path in gold_files
    }
    measured = {
        path: analysis
        for path, analysis in known_analyses.items()
        if analysis.status == EvaluationMeasurementStatus.MEASURED
    }
    failed_files = sorted(
        path
        for path, analysis in known_analyses.items()
        if analysis.status == EvaluationMeasurementStatus.FAILED
    )
    unevaluated_files = sorted(
        path
        for path in gold_files
        if path not in known_analyses
        or known_analyses[path].status
        not in {
            EvaluationMeasurementStatus.MEASURED,
            EvaluationMeasurementStatus.FAILED,
        }
    )

    relevance_counts = relevance_classification_counts(gold_files, measured)
    all_obligations = scorable_obligations(gold_files.values())
    completed_obligations = scorable_obligations(
        gold_files[path] for path in measured
    )
    obligation_ids = [obligation.id for obligation in all_obligations]
    ensure_unique(obligation_ids, "gold obligation id")
    gold_by_path = {
        path: {obligation.id: obligation for obligation in file.obligations}
        for path, file in gold_files.items()
    }

    claim_assessment = assess_claims(measured, gold_by_path)
    covered_ids = claim_assessment.covered_obligation_ids
    completed_obligation_ids = {item.id for item in completed_obligations}
    unevaluated_gold_obligation_ids = sorted(
        set(obligation_ids).difference(completed_obligation_ids)
    )
    missed_critical_obligation_ids = sorted(
        obligation.id
        for obligation in completed_obligations
        if obligation.severity == DocumentationObligationSeverity.CRITICAL
        and obligation.id not in covered_ids
    )

    evidence_refs = evidence_references(measured.values())
    available_evidence_refs = set(evaluation_input.available_evidence_refs)
    invalid_evidence_refs = sorted(evidence_refs.difference(available_evidence_refs))
    valid_claim_evidence = sum(
        claim_has_valid_evidence(claim, available_evidence_refs)
        for analysis in measured.values()
        for claim in analysis.claims
    )
    claims = [
        claim
        for analysis in measured.values()
        for claim in analysis.claims
    ]

    metrics = [
        ratio_metric(
            "analysis_completion_coverage",
            len(measured),
            len(gold_files),
        ),
        ratio_metric(
            "analysis_failure_rate",
            len(failed_files),
            len(gold_files),
        ),
        ratio_metric(
            "adjudicated_gold_coverage",
            sum(
                obligation.adjudication_status
                == EvaluationAdjudicationStatus.ADJUDICATED
                for file in gold_files.values()
                for obligation in file.obligations
            ),
            sum(len(file.obligations) for file in gold_files.values()),
        ),
        ratio_metric(
            "scorable_gold_coverage",
            len(all_obligations),
            sum(len(file.obligations) for file in gold_files.values()),
        ),
        ratio_metric(
            "evaluable_obligation_coverage",
            len(completed_obligations),
            len(all_obligations),
        ),
        *named_classification_metrics("relevance", relevance_counts),
        *named_classification_metrics(
            "obligation",
            claim_assessment.counts,
        ),
        weighted_obligation_recall(completed_obligations, covered_ids),
        ratio_metric(
            "unsupported_claim_rate",
            len(claim_assessment.unsupported_claim_ids),
            len(claims),
        ),
        ratio_metric(
            "duplicate_claim_rate",
            len(claim_assessment.duplicate_claim_ids),
            len(claims),
        ),
        ratio_metric(
            "claim_valid_evidence_coverage",
            valid_claim_evidence,
            len(claims),
        ),
        ratio_metric(
            "evidence_ref_validity",
            len(evidence_refs.intersection(available_evidence_refs)),
            len(evidence_refs),
        ),
    ]
    findings.extend(
        gold_status_findings(
            (
                obligation.adjudication_status
                for file in gold_files.values()
                for obligation in file.obligations
            ),
            label="gold obligations",
        )
    )
    if claim_assessment.invalid_gold_obligation_refs:
        findings.append(
            f"{len(claim_assessment.invalid_gold_obligation_refs)} claim-to-gold refs are invalid"
        )

    return ChangeImpactEvaluationReport(
        case_id=evaluation_input.gold.case_id,
        gold_version=evaluation_input.gold.gold_version,
        relevance_counts=relevance_counts,
        metrics=metrics,
        obligation_by_severity=severity_results(
            completed_obligations,
            claim_assessment.claims_by_severity,
        ),
        unsupported_claim_ids=sorted(claim_assessment.unsupported_claim_ids),
        unmatched_claim_ids=sorted(claim_assessment.unmatched_claim_ids),
        duplicate_claim_ids=sorted(claim_assessment.duplicate_claim_ids),
        missed_critical_obligation_ids=missed_critical_obligation_ids,
        unevaluated_gold_obligation_ids=unevaluated_gold_obligation_ids,
        invalid_evidence_refs=invalid_evidence_refs,
        invalid_gold_obligation_refs=sorted(
            claim_assessment.invalid_gold_obligation_refs
        ),
        failed_files=failed_files,
        unevaluated_files=unevaluated_files,
        findings=findings,
    )


def relevance_classification_counts(
    gold_files: dict[str, ChangeImpactGoldFile],
    measured: dict[str, ChangeImpactFileAnalysis],
) -> BinaryClassificationCounts:
    counts = BinaryClassificationCounts()
    for path, analysis in measured.items():
        expected = gold_files[path].documentation_relevant
        predicted = analysis.predicted_documentation_relevant
        if expected and predicted:
            counts.true_positive += 1
        elif not expected and predicted:
            counts.false_positive += 1
        elif expected and not predicted:
            counts.false_negative += 1
        else:
            counts.true_negative += 1
    return counts


def weighted_obligation_recall(
    obligations: list[ChangeImpactGoldObligation],
    covered_ids: set[str],
) -> EvaluationMetric:
    denominator = sum(SEVERITY_WEIGHTS[item.severity] for item in obligations)
    numerator = sum(
        SEVERITY_WEIGHTS[item.severity]
        for item in obligations
        if item.id in covered_ids
    )
    return ratio_metric("severity_weighted_obligation_recall", numerator, denominator)


def scorable_obligations(
    files: Iterable[ChangeImpactGoldFile],
) -> list[ChangeImpactGoldObligation]:
    return [
        obligation
        for file in files
        for obligation in file.obligations
        if is_scorable_gold(obligation.adjudication_status)
    ]


def evidence_references(analyses: Iterable[ChangeImpactFileAnalysis]) -> set[str]:
    return {
        reference
        for analysis in analyses
        for reference in [
            *analysis.evidence_refs,
            *(ref for claim in analysis.claims for ref in claim.evidence_refs),
        ]
    }


def claim_has_valid_evidence(
    claim: ChangeImpactPredictedClaim,
    available_evidence_refs: set[str],
) -> bool:
    return bool(claim.evidence_refs) and set(claim.evidence_refs).issubset(
        available_evidence_refs
    )


def unique_gold_files(items: Iterable[ChangeImpactGoldFile]) -> dict[str, ChangeImpactGoldFile]:
    result: dict[str, ChangeImpactGoldFile] = {}
    for item in items:
        if item.path in result:
            raise ValueError(f"duplicate path: {item.path}")
        result[item.path] = item
    return result


def unique_analyses(
    items: Iterable[ChangeImpactFileAnalysis],
) -> dict[str, ChangeImpactFileAnalysis]:
    result: dict[str, ChangeImpactFileAnalysis] = {}
    for item in items:
        if item.path in result:
            raise ValueError(f"duplicate path: {item.path}")
        result[item.path] = item
    return result


def ensure_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)
