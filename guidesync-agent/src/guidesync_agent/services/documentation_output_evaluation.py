from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from guidesync_agent.schemas import (
    BinaryClassificationCounts,
    ChangeImpactGoldObligation,
    DocumentationGenerationEvaluationInput,
    DocumentationGenerationEvaluationReport,
    DocumentationPlanningEvaluationInput,
    DocumentationPlanningEvaluationReport,
    DocumentationTargetGold,
    DocumentationTargetPrediction,
    EvaluationMeasurementStatus,
    EvaluationMetric,
    GeneratedClaimRelevance,
    GeneratedClaimSupport,
)
from guidesync_agent.services.change_impact_evaluation import SEVERITY_WEIGHTS
from guidesync_agent.services.evaluation_adjudication import (
    gold_status_findings,
    is_scorable_gold,
)
from guidesync_agent.services.evaluation_metrics import (
    f_beta_from_metrics,
    f_beta_metric,
    failed_metric,
    not_evaluated_metric,
    precision_metric,
    ratio_metric,
    recall_metric,
)


@dataclass
class DocumentationPlanningMatches:
    planned_keys: set[tuple[str, str, str]] = field(default_factory=set)
    matched_paths: set[str] = field(default_factory=set)
    true_positive: int = 0
    false_positive: int = 0
    wrong_action_ids: list[str] = field(default_factory=list)
    wrong_section_ids: list[str] = field(default_factory=list)
    unnecessary_ids: list[str] = field(default_factory=list)
    valid_evidence_items: int = 0
    evidence_refs: set[str] = field(default_factory=set)


def evaluate_documentation_planning(
    evaluation_input: DocumentationPlanningEvaluationInput,
) -> DocumentationPlanningEvaluationReport:
    gold_by_path = unique_gold_targets(evaluation_input.gold_targets)
    available_evidence_refs = set(evaluation_input.available_evidence_refs)
    matches = match_documentation_plans(
        evaluation_input,
        gold_by_path,
        available_evidence_refs,
    )

    target_counts = BinaryClassificationCounts(
        true_positive=matches.true_positive,
        false_positive=matches.false_positive,
        false_negative=len(set(gold_by_path).difference(matches.matched_paths)),
    )
    executed_keys = {target_key(target) for target in evaluation_input.executed_targets}
    plan_execution_intersection = matches.planned_keys.intersection(executed_keys)
    planned_not_executed_ids = sorted(
        plan.id
        for plan in evaluation_input.planned_targets
        if target_key(plan) not in executed_keys
    )
    unplanned_executed_ids = sorted(
        target.id
        for target in evaluation_input.executed_targets
        if target_key(target) not in matches.planned_keys
    )
    matched_gold = len(matches.matched_paths)
    correct_action = matched_gold - len(matches.wrong_action_ids)
    gold_sections = sum(
        gold_by_path[path].section is not None for path in matches.matched_paths
    )
    wrong_expected_sections = sum(
        gold_by_path[normalize_path(plan.path)].section is not None
        for plan in evaluation_input.planned_targets
        if plan.id in matches.wrong_section_ids
        and normalize_path(plan.path) in gold_by_path
    )
    metrics = [
        *named_classification_metrics("target_document", target_counts),
        ratio_metric("create_update_accuracy", correct_action, matched_gold),
        ratio_metric(
            "target_section_accuracy",
            gold_sections - wrong_expected_sections,
            gold_sections,
        ),
        ratio_metric(
            "plan_evidence_coverage",
            matches.valid_evidence_items,
            len(evaluation_input.planned_targets),
        ),
        ratio_metric(
            "plan_evidence_ref_validity",
            len(matches.evidence_refs.intersection(available_evidence_refs)),
            len(matches.evidence_refs),
        ),
        ratio_metric(
            "plan_execution_precision",
            len(plan_execution_intersection),
            len(executed_keys),
        ),
        ratio_metric(
            "plan_execution_recall",
            len(plan_execution_intersection),
            len(matches.planned_keys),
        ),
        ratio_metric(
            "plan_execution_jaccard",
            len(plan_execution_intersection),
            len(matches.planned_keys.union(executed_keys)),
        ),
    ]
    return DocumentationPlanningEvaluationReport(
        case_id=evaluation_input.case_id,
        metrics=metrics,
        missing_target_ids=sorted(
            gold.id
            for path, gold in gold_by_path.items()
            if path not in matches.matched_paths
        ),
        unnecessary_plan_ids=sorted(matches.unnecessary_ids),
        wrong_action_plan_ids=sorted(matches.wrong_action_ids),
        wrong_section_plan_ids=sorted(matches.wrong_section_ids),
        invalid_evidence_refs=sorted(
            matches.evidence_refs.difference(available_evidence_refs)
        ),
        planned_not_executed_ids=planned_not_executed_ids,
        unplanned_executed_ids=unplanned_executed_ids,
    )


def match_documentation_plans(
    evaluation_input: DocumentationPlanningEvaluationInput,
    gold_by_path: dict[str, DocumentationTargetGold],
    available_evidence_refs: set[str],
) -> DocumentationPlanningMatches:
    matches = DocumentationPlanningMatches()
    for plan in evaluation_input.planned_targets:
        matches.planned_keys.add(target_key(plan))
        matches.evidence_refs.update(plan.evidence_refs)
        if plan.evidence_refs and set(plan.evidence_refs).issubset(available_evidence_refs):
            matches.valid_evidence_items += 1
        path = normalize_path(plan.path)
        gold = gold_by_path.get(path)
        if gold is None or path in matches.matched_paths:
            matches.false_positive += 1
            matches.unnecessary_ids.append(plan.id)
            continue
        matches.true_positive += 1
        matches.matched_paths.add(path)
        if plan.action != gold.action:
            matches.wrong_action_ids.append(plan.id)
        if normalized_section(plan.section) != normalized_section(gold.section):
            matches.wrong_section_ids.append(plan.id)
    return matches


def evaluate_documentation_generation(
    evaluation_input: DocumentationGenerationEvaluationInput,
) -> DocumentationGenerationEvaluationReport:
    metric_names = [
        "atomic_claim_precision",
        "unsupported_claim_rate",
        "weighted_obligation_recall",
        "visual_obligation_recall",
        "output_f1",
        "output_f0.5",
        "claim_traceability",
        "edit_scope_precision",
        "planned_scope_coverage",
        "surrounding_content_preservation",
        "structural_validation_pass_rate",
    ]
    if evaluation_input.status != EvaluationMeasurementStatus.MEASURED:
        return DocumentationGenerationEvaluationReport(
            case_id=evaluation_input.case_id,
            status=evaluation_input.status,
            metrics=unmeasured_metrics(
                metric_names,
                evaluation_input.status,
                "documentation generation did not produce a measurable output",
            ),
            output_artifact_ref=evaluation_input.output_artifact_ref,
        )

    obligations = [
        obligation
        for obligation in evaluation_input.gold_obligations
        if is_scorable_gold(obligation.adjudication_status)
    ]
    ensure_unique((item.id for item in obligations), "gold obligation id")
    gold_by_id = {item.id: item for item in obligations}
    visual_fact_ids = {
        fact_id for obligation in obligations for fact_id in obligation.visual_fact_ids
    }
    supported_relevant = [
        claim
        for claim in evaluation_input.claims
        if claim.support == GeneratedClaimSupport.SUPPORTED
        and claim.relevance == GeneratedClaimRelevance.RELEVANT
    ]
    contradicted_ids = sorted(
        claim.id
        for claim in evaluation_input.claims
        if claim.support == GeneratedClaimSupport.CONTRADICTED
    )
    unsupported_ids = sorted(
        claim.id
        for claim in evaluation_input.claims
        if claim.support != GeneratedClaimSupport.SUPPORTED
    )
    irrelevant_ids = sorted(
        claim.id
        for claim in evaluation_input.claims
        if claim.relevance == GeneratedClaimRelevance.IRRELEVANT
    )
    covered: set[str] = set()
    duplicate_ids: list[str] = []
    for claim in supported_relevant:
        valid_ids = set(claim.matched_gold_obligation_ids).intersection(gold_by_id)
        grounded_ids = {
            obligation_id
            for obligation_id in valid_ids
            if not gold_by_id[obligation_id].visual_fact_ids
            or set(gold_by_id[obligation_id].visual_fact_ids).intersection(
                claim.matched_visual_fact_ids
            )
        }
        if grounded_ids and not grounded_ids.difference(covered):
            duplicate_ids.append(claim.id)
        covered.update(grounded_ids)

    claim_precision = ratio_metric(
        "atomic_claim_precision",
        len(supported_relevant),
        len(evaluation_input.claims),
    )
    weighted_recall = weighted_obligation_recall(obligations, covered)
    visual_obligations = [item for item in obligations if item.visual_fact_ids]
    available_evidence_refs = set(evaluation_input.available_evidence_refs)
    evidence_refs = {
        reference
        for claim in evaluation_input.claims
        for reference in claim.evidence_refs
    }
    traceable_claims = sum(
        bool(claim.evidence_refs)
        and set(claim.evidence_refs).issubset(available_evidence_refs)
        for claim in evaluation_input.claims
    )
    planned_scope = set(evaluation_input.planned_scope_ids)
    changed_scope = set(evaluation_input.changed_scope_ids)
    altered_surrounding = sorted(
        item.id
        for item in evaluation_input.preservation_checks
        if item.before_hash != item.after_hash
    )
    failed_structure = sorted(
        item.id for item in evaluation_input.structural_checks if not item.passed
    )
    metrics = [
        claim_precision,
        ratio_metric(
            "unsupported_claim_rate",
            len(unsupported_ids),
            len(evaluation_input.claims),
        ),
        weighted_recall,
        weighted_obligation_recall(visual_obligations, covered).model_copy(
            update={"name": "visual_obligation_recall"}
        ),
        f_beta_from_metrics(
            claim_precision,
            weighted_recall,
            name="output_f1",
        ),
        f_beta_from_metrics(
            claim_precision,
            weighted_recall,
            beta=0.5,
            name="output_f0.5",
        ),
        ratio_metric(
            "claim_traceability",
            traceable_claims,
            len(evaluation_input.claims),
        ),
        ratio_metric(
            "edit_scope_precision",
            len(planned_scope.intersection(changed_scope)),
            len(changed_scope),
        ),
        ratio_metric(
            "planned_scope_coverage",
            len(planned_scope.intersection(changed_scope)),
            len(planned_scope),
        ),
        ratio_metric(
            "surrounding_content_preservation",
            len(evaluation_input.preservation_checks) - len(altered_surrounding),
            len(evaluation_input.preservation_checks),
        ),
        ratio_metric(
            "structural_validation_pass_rate",
            len(evaluation_input.structural_checks) - len(failed_structure),
            len(evaluation_input.structural_checks),
        ),
    ]
    return DocumentationGenerationEvaluationReport(
        case_id=evaluation_input.case_id,
        status=evaluation_input.status,
        metrics=metrics,
        missing_obligation_ids=sorted(set(gold_by_id).difference(covered)),
        unsupported_claim_ids=unsupported_ids,
        contradicted_claim_ids=contradicted_ids,
        irrelevant_claim_ids=irrelevant_ids,
        duplicate_claim_ids=sorted(duplicate_ids),
        invalid_evidence_refs=sorted(evidence_refs.difference(available_evidence_refs)),
        invalid_visual_fact_ids=sorted(
            {
                fact_id
                for claim in evaluation_input.claims
                for fact_id in claim.matched_visual_fact_ids
            }.difference(visual_fact_ids)
        ),
        unplanned_changed_scope_ids=sorted(changed_scope.difference(planned_scope)),
        altered_surrounding_content_ids=altered_surrounding,
        failed_structural_check_ids=failed_structure,
        output_artifact_ref=evaluation_input.output_artifact_ref,
        findings=gold_status_findings(
            (
                obligation.adjudication_status
                for obligation in evaluation_input.gold_obligations
            ),
            label="gold obligations",
        ),
    )


def named_classification_metrics(
    prefix: str,
    counts: BinaryClassificationCounts,
) -> list[EvaluationMetric]:
    return [
        precision_metric(counts).model_copy(update={"name": f"{prefix}_precision"}),
        recall_metric(counts).model_copy(update={"name": f"{prefix}_recall"}),
        f_beta_metric(counts).model_copy(update={"name": f"{prefix}_f1"}),
    ]


def weighted_obligation_recall(
    obligations: Sequence[ChangeImpactGoldObligation],
    covered_ids: set[str],
) -> EvaluationMetric:
    denominator = sum(SEVERITY_WEIGHTS[item.severity] for item in obligations)
    numerator = sum(
        SEVERITY_WEIGHTS[item.severity]
        for item in obligations
        if item.id in covered_ids
    )
    return ratio_metric("weighted_obligation_recall", numerator, denominator)


def unmeasured_metrics(
    names: Sequence[str],
    status: EvaluationMeasurementStatus,
    reason: str,
) -> list[EvaluationMetric]:
    factory = (
        failed_metric
        if status == EvaluationMeasurementStatus.FAILED
        else not_evaluated_metric
    )
    return [factory(name, reason) for name in names]


def target_key(target: DocumentationTargetPrediction) -> tuple[str, str, str]:
    return (
        normalize_path(target.path),
        target.action.value,
        normalized_section(target.section),
    )


def unique_gold_targets(
    targets: Iterable[DocumentationTargetGold],
) -> dict[str, DocumentationTargetGold]:
    result: dict[str, DocumentationTargetGold] = {}
    for target in targets:
        path = normalize_path(target.path)
        if path in result:
            raise ValueError(f"duplicate gold target path: {path}")
        result[path] = target
    return result


def normalized_section(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def normalize_path(value: str) -> str:
    return value.strip().replace("\\", "/").removeprefix("./").lstrip("/")


def ensure_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)
