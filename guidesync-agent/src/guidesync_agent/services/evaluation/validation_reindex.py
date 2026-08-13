from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from guidesync_agent.schemas import (
    BinaryClassificationCounts,
    EvaluationMeasurementStatus,
    EvaluationMetric,
    ReindexEvaluationInput,
    ReindexEvaluationReport,
    ReindexGoldDocument,
    ReindexObservedDocument,
    ValidationEvaluationInput,
    ValidationEvaluationReport,
)
from guidesync_agent.services.evaluation.adjudication import (
    gold_status_findings,
    is_scorable_gold,
)
from guidesync_agent.services.evaluation.metrics import (
    f_beta_metric,
    failed_metric,
    not_evaluated_metric,
    precision_metric,
    ratio_metric,
    recall_metric,
)


@dataclass
class ReindexCoverage:
    total_expected_sections: int = 0
    evaluable_sections: int = 0
    matched_sections: int = 0
    total_expected_queries: int = 0
    evaluable_queries: int = 0
    successful_queries: int = 0
    missing_sections: list[str] = field(default_factory=list)
    failed_queries: list[str] = field(default_factory=list)


def evaluate_validation(
    evaluation_input: ValidationEvaluationInput,
) -> ValidationEvaluationReport:
    gold_defects = [
        defect
        for defect in evaluation_input.gold_defects
        if is_scorable_gold(defect.adjudication_status)
    ]
    ensure_unique((item.id for item in gold_defects), "gold defect id")
    gold_ids = {item.id for item in gold_defects}
    if evaluation_input.status != EvaluationMeasurementStatus.MEASURED:
        return ValidationEvaluationReport(
            case_id=evaluation_input.case_id,
            status=evaluation_input.status,
            detection_counts=BinaryClassificationCounts(),
            metrics=unmeasured_metrics(
                [
                    "defect_detection_precision",
                    "defect_detection_recall",
                    "defect_detection_f1",
                    "validator_false_positive_rate",
                    "defect_correction_rate",
                    "residual_defect_rate",
                ],
                evaluation_input.status,
                "validator did not produce measurable findings",
            ),
            pre_validation_artifact_ref=evaluation_input.pre_validation_artifact_ref,
            post_validation_artifact_ref=evaluation_input.post_validation_artifact_ref,
        )

    covered: set[str] = set()
    false_positive_ids: list[str] = []
    duplicate_ids: list[str] = []
    invalid_gold_refs: set[str] = set()
    for finding in evaluation_input.findings:
        referenced = set(finding.matched_gold_defect_ids)
        valid = referenced.intersection(gold_ids)
        invalid_gold_refs.update(
            f"{finding.id}:{defect_id}" for defect_id in referenced.difference(gold_ids)
        )
        new_ids = valid.difference(covered)
        if not valid:
            false_positive_ids.append(finding.id)
        elif not new_ids:
            false_positive_ids.append(finding.id)
            duplicate_ids.append(finding.id)
        covered.update(new_ids)
    counts = BinaryClassificationCounts(
        true_positive=len(evaluation_input.findings) - len(false_positive_ids),
        false_positive=len(false_positive_ids),
        false_negative=len(gold_ids.difference(covered)),
    )
    corrected_refs = set(evaluation_input.corrected_gold_defect_ids)
    residual_refs = set(evaluation_input.residual_gold_defect_ids)
    invalid_gold_refs.update(
        f"correction:{defect_id}" for defect_id in corrected_refs.difference(gold_ids)
    )
    invalid_gold_refs.update(
        f"residual:{defect_id}" for defect_id in residual_refs.difference(gold_ids)
    )
    corrected = corrected_refs.intersection(gold_ids)
    residual = residual_refs.intersection(gold_ids)
    evidence_refs = {
        reference
        for finding in evaluation_input.findings
        for reference in finding.evidence_refs
    }
    available_evidence_refs = set(evaluation_input.available_evidence_refs)
    metrics = [
        *named_classification_metrics("defect_detection", counts),
        ratio_metric(
            "validator_false_positive_rate",
            len(false_positive_ids),
            len(evaluation_input.findings),
        ),
        ratio_metric(
            "defect_correction_rate",
            len(corrected.intersection(covered)),
            len(covered),
        ),
        ratio_metric(
            "residual_defect_rate",
            len(residual),
            len(gold_ids),
        ),
    ]
    return ValidationEvaluationReport(
        case_id=evaluation_input.case_id,
        status=evaluation_input.status,
        detection_counts=counts,
        metrics=metrics,
        missed_defect_ids=sorted(gold_ids.difference(covered)),
        false_positive_finding_ids=sorted(false_positive_ids),
        duplicate_finding_ids=sorted(duplicate_ids),
        invalid_evidence_refs=sorted(evidence_refs.difference(available_evidence_refs)),
        invalid_gold_defect_refs=sorted(invalid_gold_refs),
        pre_validation_artifact_ref=evaluation_input.pre_validation_artifact_ref,
        post_validation_artifact_ref=evaluation_input.post_validation_artifact_ref,
        findings=gold_status_findings(
            (defect.adjudication_status for defect in evaluation_input.gold_defects),
            label="gold defects",
        ),
    )


def evaluate_reindex(
    evaluation_input: ReindexEvaluationInput,
) -> ReindexEvaluationReport:
    metric_names = [
        "changed_document_reindex_coverage",
        "indexed_commit_accuracy",
        "indexed_content_hash_accuracy",
        "section_evaluation_coverage",
        "reindexed_section_coverage",
        "query_evaluation_coverage",
        "post_edit_query_success",
    ]
    if evaluation_input.status != EvaluationMeasurementStatus.MEASURED:
        return ReindexEvaluationReport(
            case_id=evaluation_input.case_id,
            status=evaluation_input.status,
            metrics=unmeasured_metrics(
                metric_names,
                evaluation_input.status,
                "post-edit reindex did not produce a measurable snapshot",
            ),
        )

    gold_by_path = unique_gold_documents(evaluation_input.gold_documents)
    observed_by_path = unique_observed_documents(evaluation_input.observed_documents)
    matched_paths = set(gold_by_path).intersection(observed_by_path)
    missing_paths = set(gold_by_path).difference(observed_by_path)
    unexpected_paths = set(observed_by_path).difference(gold_by_path)
    stale_commits = sorted(
        path
        for path in matched_paths
        if observed_by_path[path].indexed_commit != gold_by_path[path].expected_commit
    )
    stale_content = sorted(
        path
        for path in matched_paths
        if observed_by_path[path].indexed_content_hash
        != gold_by_path[path].expected_content_hash
    )
    coverage = calculate_reindex_coverage(
        gold_by_path,
        observed_by_path,
        matched_paths,
        missing_paths,
    )

    metrics = [
        ratio_metric(
            "changed_document_reindex_coverage",
            len(matched_paths),
            len(gold_by_path),
        ),
        ratio_metric(
            "indexed_commit_accuracy",
            len(matched_paths) - len(stale_commits),
            len(matched_paths),
        ),
        ratio_metric(
            "indexed_content_hash_accuracy",
            len(matched_paths) - len(stale_content),
            len(matched_paths),
        ),
        ratio_metric(
            "section_evaluation_coverage",
            coverage.evaluable_sections,
            coverage.total_expected_sections,
        ),
        ratio_metric(
            "reindexed_section_coverage",
            coverage.matched_sections,
            coverage.evaluable_sections,
        ),
        ratio_metric(
            "query_evaluation_coverage",
            coverage.evaluable_queries,
            coverage.total_expected_queries,
        ),
        ratio_metric(
            "post_edit_query_success",
            coverage.successful_queries,
            coverage.evaluable_queries,
        ),
    ]
    return ReindexEvaluationReport(
        case_id=evaluation_input.case_id,
        status=evaluation_input.status,
        metrics=metrics,
        missing_document_paths=sorted(missing_paths),
        unexpected_document_paths=sorted(unexpected_paths),
        stale_commit_paths=stale_commits,
        stale_content_paths=stale_content,
        missing_section_refs=sorted(coverage.missing_sections),
        failed_query_ids=sorted(coverage.failed_queries),
    )


def calculate_reindex_coverage(
    gold_by_path: dict[str, ReindexGoldDocument],
    observed_by_path: dict[str, ReindexObservedDocument],
    matched_paths: set[str],
    missing_paths: set[str],
) -> ReindexCoverage:
    coverage = ReindexCoverage(
        total_expected_sections=sum(
            len(document.expected_sections) for document in gold_by_path.values()
        ),
        total_expected_queries=sum(
            len(document.expected_query_ids) for document in gold_by_path.values()
        ),
    )
    for path in matched_paths:
        gold = gold_by_path[path]
        observed = observed_by_path[path]
        observed_sections = set(observed.indexed_sections)
        coverage.evaluable_sections += len(gold.expected_sections)
        coverage.matched_sections += len(
            set(gold.expected_sections).intersection(observed_sections)
        )
        coverage.missing_sections.extend(
            f"{path}#{section}"
            for section in gold.expected_sections
            if section not in observed_sections
        )
        observed_queries = set(observed.successful_query_ids)
        coverage.evaluable_queries += len(gold.expected_query_ids)
        coverage.successful_queries += len(
            set(gold.expected_query_ids).intersection(observed_queries)
        )
        coverage.failed_queries.extend(
            f"{path}:{query_id}"
            for query_id in gold.expected_query_ids
            if query_id not in observed_queries
        )
    for path in missing_paths:
        gold = gold_by_path[path]
        coverage.missing_sections.extend(
            f"{path}#{section}" for section in gold.expected_sections
        )
        coverage.failed_queries.extend(
            f"{path}:{query_id}" for query_id in gold.expected_query_ids
        )

    return coverage


def named_classification_metrics(
    prefix: str,
    counts: BinaryClassificationCounts,
) -> list[EvaluationMetric]:
    return [
        precision_metric(counts).model_copy(update={"name": f"{prefix}_precision"}),
        recall_metric(counts).model_copy(update={"name": f"{prefix}_recall"}),
        f_beta_metric(counts).model_copy(update={"name": f"{prefix}_f1"}),
    ]


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


def unique_gold_documents(
    documents: Iterable[ReindexGoldDocument],
) -> dict[str, ReindexGoldDocument]:
    result: dict[str, ReindexGoldDocument] = {}
    for document in documents:
        path = normalize_path(document.path)
        if path in result:
            raise ValueError(f"duplicate reindex gold path: {path}")
        result[path] = document
    return result


def unique_observed_documents(
    documents: Iterable[ReindexObservedDocument],
) -> dict[str, ReindexObservedDocument]:
    result: dict[str, ReindexObservedDocument] = {}
    for document in documents:
        path = normalize_path(document.path)
        if path in result:
            raise ValueError(f"duplicate reindex observed path: {path}")
        result[path] = document
    return result


def normalize_path(value: str) -> str:
    return value.strip().replace("\\", "/").removeprefix("./").lstrip("/")


def ensure_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)
