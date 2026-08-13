from __future__ import annotations

from guidesync_agent.schemas import (
    BinaryClassificationCounts,
    ChangeImpactClaimSupport,
    ChangeImpactFileAnalysis,
    ChangeImpactGoldObligation,
    ChangeImpactPredictedClaim,
    ChangeImpactSeverityResult,
    DocumentationObligationSeverity,
    EvaluationMetric,
)
from guidesync_agent.services.evaluation.adjudication import is_scorable_gold
from guidesync_agent.services.evaluation.metrics import (
    f_beta_metric,
    precision_metric,
    recall_metric,
)


class ClaimAssessment:
    def __init__(self) -> None:
        self.counts = BinaryClassificationCounts()
        self.covered_obligation_ids: set[str] = set()
        self.unsupported_claim_ids: set[str] = set()
        self.unmatched_claim_ids: set[str] = set()
        self.duplicate_claim_ids: set[str] = set()
        self.invalid_gold_obligation_refs: set[str] = set()
        self.claims_by_severity: dict[
            DocumentationObligationSeverity,
            list[tuple[ChangeImpactPredictedClaim, set[str]]],
        ] = {severity: [] for severity in DocumentationObligationSeverity}


def assess_claims(
    measured: dict[str, ChangeImpactFileAnalysis],
    gold_by_path: dict[str, dict[str, ChangeImpactGoldObligation]],
) -> ClaimAssessment:
    assessment = ClaimAssessment()
    for path, analysis in measured.items():
        file_gold = gold_by_path[path]
        scorable_ids = {
            obligation_id
            for obligation_id, obligation in file_gold.items()
            if is_scorable_gold(obligation.adjudication_status)
        }
        for claim in analysis.claims:
            referenced_ids = set(claim.matched_gold_obligation_ids)
            valid_ids = referenced_ids.intersection(scorable_ids)
            invalid_ids = referenced_ids.difference(file_gold)
            assessment.invalid_gold_obligation_refs.update(
                f"{claim.id}:{obligation_id}" for obligation_id in invalid_ids
            )
            new_ids = valid_ids.difference(assessment.covered_obligation_ids)
            assessment.claims_by_severity[claim.severity].append((claim, valid_ids))
            if not valid_ids:
                assessment.unmatched_claim_ids.add(claim.id)
            if claim.support != ChangeImpactClaimSupport.SUPPORTED:
                assessment.unsupported_claim_ids.add(claim.id)
                assessment.counts.false_positive += 1
                continue
            if not valid_ids:
                assessment.counts.false_positive += 1
                continue
            if not new_ids:
                assessment.duplicate_claim_ids.add(claim.id)
                assessment.counts.false_positive += 1
                continue
            assessment.counts.true_positive += 1
            assessment.covered_obligation_ids.update(new_ids)

    completed_gold_ids = {
        obligation_id
        for path in measured
        for obligation_id, obligation in gold_by_path[path].items()
        if is_scorable_gold(obligation.adjudication_status)
    }
    assessment.counts.false_negative = len(
        completed_gold_ids.difference(assessment.covered_obligation_ids)
    )
    return assessment


def severity_results(
    obligations: list[ChangeImpactGoldObligation],
    claims_by_severity: dict[
        DocumentationObligationSeverity,
        list[tuple[ChangeImpactPredictedClaim, set[str]]],
    ],
) -> list[ChangeImpactSeverityResult]:
    results: list[ChangeImpactSeverityResult] = []
    for severity in DocumentationObligationSeverity:
        gold_ids = {
            obligation.id
            for obligation in obligations
            if obligation.severity == severity
        }
        covered: set[str] = set()
        true_positive = 0
        false_positive = 0
        for claim, valid_ids in claims_by_severity[severity]:
            if claim.support != ChangeImpactClaimSupport.SUPPORTED:
                false_positive += 1
                continue
            matching_ids = {
                obligation.id
                for obligation in obligations
                if obligation.id in valid_ids and obligation.severity == severity
            }
            new_ids = matching_ids.difference(covered)
            if new_ids:
                true_positive += 1
                covered.update(new_ids)
            else:
                false_positive += 1
        counts = BinaryClassificationCounts(
            true_positive=true_positive,
            false_positive=false_positive,
            false_negative=len(gold_ids.difference(covered)),
        )
        results.append(
            ChangeImpactSeverityResult(
                severity=severity,
                counts=counts,
                metrics=named_classification_metrics(severity.value, counts),
            )
        )
    return results


def named_classification_metrics(
    prefix: str,
    counts: BinaryClassificationCounts,
) -> list[EvaluationMetric]:
    return [
        precision_metric(counts).model_copy(update={"name": f"{prefix}_precision"}),
        recall_metric(counts).model_copy(update={"name": f"{prefix}_recall"}),
        f_beta_metric(counts).model_copy(update={"name": f"{prefix}_f1"}),
    ]
