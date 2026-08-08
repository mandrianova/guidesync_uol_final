from __future__ import annotations

import re
from collections.abc import Sequence

from guidesync_agent.schemas import (
    EvaluationMetric,
    ProfileClaimLabel,
    ProfileEvidenceAccess,
    ProfileGoldLabel,
    ProjectProfileEvaluationGold,
    ProjectProfileEvaluationInput,
    ProjectProfileEvaluationReport,
)
from guidesync_agent.services.evaluation_metrics import (
    f_beta_from_metrics,
    jaccard_stability_metric,
    not_evaluated_metric,
    ratio_metric,
)


def evaluate_project_profile(
    gold: ProjectProfileEvaluationGold,
    evaluation_input: ProjectProfileEvaluationInput,
) -> ProjectProfileEvaluationReport:
    gold_fact_ids = {fact.id for fact in gold.facts}
    supported_claims = [
        claim
        for claim in evaluation_input.claims
        if claim.label == ProfileClaimLabel.SUPPORTED_RELEVANT
    ]
    unsupported_claim_ids = [
        claim.id
        for claim in evaluation_input.claims
        if claim.label
        in {
            ProfileClaimLabel.CONTRADICTED,
            ProfileClaimLabel.NOT_ENOUGH_EVIDENCE,
        }
    ]
    matched_fact_ids = {
        fact_id
        for claim in supported_claims
        for fact_id in claim.matched_gold_fact_ids
        if fact_id in gold_fact_ids
    }
    invalid_matched_fact_ids = sorted(
        {
            fact_id
            for claim in evaluation_input.claims
            for fact_id in claim.matched_gold_fact_ids
            if fact_id not in gold_fact_ids
        }
    )

    claim_precision = ratio_metric(
        "profile_claim_precision",
        len(supported_claims),
        len(evaluation_input.claims),
    )
    fact_recall = ratio_metric(
        "profile_fact_recall",
        len(matched_fact_ids),
        len(gold.facts),
    )
    metrics = [
        claim_precision,
        fact_recall,
        f_beta_from_metrics(
            claim_precision,
            fact_recall,
            name="profile_f1",
        ),
    ]
    metrics.extend(
        label_metrics(
            "category",
            evaluation_input.predicted_categories,
            gold.categories,
        )
    )
    metrics.extend(
        label_metrics(
            "concept",
            evaluation_input.predicted_concepts,
            gold.concepts,
        )
    )

    evidence_access = evidence_access_by_path(evaluation_input)
    available_paths = {
        normalize_evidence_path(path)
        for path in evaluation_input.available_repository_paths
    } or set(evidence_access)
    content_paths = {
        path
        for path, access_levels in evidence_access.items()
        if access_levels.intersection(
            {ProfileEvidenceAccess.READ, ProfileEvidenceAccess.SEARCHED}
        )
    }
    evidence_refs = {
        normalize_evidence_path(evidence_ref)
        for claim in evaluation_input.claims
        for evidence_ref in claim.evidence_refs
    }
    invalid_evidence_refs = sorted(evidence_refs.difference(available_paths))
    listed_only_evidence_refs = sorted(
        path
        for path in evidence_refs
        if ProfileEvidenceAccess.LISTED in evidence_access.get(path, set())
        and path not in content_paths
    )
    verifiable_claims = [
        claim
        for claim in evaluation_input.claims
        if claim.label != ProfileClaimLabel.IRRELEVANT
    ]
    claims_with_content_evidence = sum(
        has_content_evidence(claim.evidence_refs, content_paths, available_paths)
        for claim in verifiable_claims
    )
    metrics.append(
        ratio_metric(
            "profile_evidence_coverage",
            claims_with_content_evidence,
            len(verifiable_claims),
        )
    )

    critical_paths = {
        normalize_evidence_path(path) for path in gold.critical_repository_paths
    }
    missing_critical_paths = sorted(critical_paths.difference(content_paths))
    metrics.append(
        ratio_metric(
            "critical_path_coverage",
            len(critical_paths) - len(missing_critical_paths),
            len(critical_paths),
        )
    )
    metrics.extend(stability_metrics(evaluation_input))

    missing_gold_fact_ids = sorted(gold_fact_ids.difference(matched_fact_ids))
    findings = profile_findings(
        unsupported_claim_ids=unsupported_claim_ids,
        missing_gold_fact_ids=missing_gold_fact_ids,
        missing_critical_paths=missing_critical_paths,
        invalid_evidence_refs=invalid_evidence_refs,
        listed_only_evidence_refs=listed_only_evidence_refs,
        invalid_matched_fact_ids=invalid_matched_fact_ids,
    )
    return ProjectProfileEvaluationReport(
        profile_id=evaluation_input.profile_id,
        gold_version=gold.version,
        adjudication_status=gold.adjudication_status,
        metrics=metrics,
        unsupported_claim_ids=unsupported_claim_ids,
        missing_gold_fact_ids=missing_gold_fact_ids,
        missing_critical_paths=missing_critical_paths,
        invalid_evidence_refs=invalid_evidence_refs,
        listed_only_evidence_refs=listed_only_evidence_refs,
        findings=findings,
    )


def label_metrics(
    prefix: str,
    predicted_values: Sequence[str],
    gold_labels: Sequence[ProfileGoldLabel],
) -> list[EvaluationMetric]:
    gold_by_value = {
        normalize_label(candidate): label.id
        for label in gold_labels
        for candidate in [label.value, *label.aliases]
    }
    matched_gold_ids: set[str] = set()
    false_positive_count = 0
    for predicted in stable_normalized_values(predicted_values):
        gold_id = gold_by_value.get(predicted)
        if gold_id is None or gold_id in matched_gold_ids:
            false_positive_count += 1
            continue
        matched_gold_ids.add(gold_id)
    true_positive_count = len(matched_gold_ids)
    precision = ratio_metric(
        f"{prefix}_precision",
        true_positive_count,
        true_positive_count + false_positive_count,
    )
    recall = ratio_metric(
        f"{prefix}_recall",
        true_positive_count,
        len(gold_labels),
    )
    return [
        precision,
        recall,
        f_beta_from_metrics(precision, recall, name=f"{prefix}_f1"),
    ]


def evidence_access_by_path(
    evaluation_input: ProjectProfileEvaluationInput,
) -> dict[str, set[ProfileEvidenceAccess]]:
    result: dict[str, set[ProfileEvidenceAccess]] = {}
    for evidence_use in evaluation_input.evidence_uses:
        path = normalize_evidence_path(evidence_use.path)
        result.setdefault(path, set()).add(evidence_use.access)
    return result


def has_content_evidence(
    evidence_refs: Sequence[str],
    content_paths: set[str],
    available_paths: set[str],
) -> bool:
    return any(
        (path := normalize_evidence_path(evidence_ref)) in content_paths
        and path in available_paths
        for evidence_ref in evidence_refs
    )


def stability_metrics(
    evaluation_input: ProjectProfileEvaluationInput,
) -> list[EvaluationMetric]:
    category_stability = (
        jaccard_stability_metric(
            stable_normalized_values(evaluation_input.predicted_categories),
            stable_normalized_values(evaluation_input.comparison_categories),
        ).model_copy(update={"name": "category_jaccard_stability"})
        if evaluation_input.comparison_categories is not None
        else not_evaluated_metric(
            "category_jaccard_stability",
            "no comparison profile categories were supplied",
        )
    )
    concept_stability = (
        jaccard_stability_metric(
            stable_normalized_values(evaluation_input.predicted_concepts),
            stable_normalized_values(evaluation_input.comparison_concepts),
        ).model_copy(update={"name": "concept_jaccard_stability"})
        if evaluation_input.comparison_concepts is not None
        else not_evaluated_metric(
            "concept_jaccard_stability",
            "no comparison profile concepts were supplied",
        )
    )
    return [category_stability, concept_stability]


def normalize_evidence_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    if normalized.startswith("/repositories/"):
        parts = normalized.split("/", 3)
        normalized = parts[3] if len(parts) == 4 else ""
    normalized = normalized.removeprefix("./").lstrip("/")
    normalized = normalized.split("#L", 1)[0]
    return re.sub(r":\d+(?::\d+)?$", "", normalized)


def normalize_label(value: str) -> str:
    return " ".join(value.casefold().split())


def stable_normalized_values(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(normalize_label(value) for value in values if value.strip()))


def profile_findings(  # noqa: PLR0913 - explicit independent finding groups
    *,
    unsupported_claim_ids: list[str],
    missing_gold_fact_ids: list[str],
    missing_critical_paths: list[str],
    invalid_evidence_refs: list[str],
    listed_only_evidence_refs: list[str],
    invalid_matched_fact_ids: list[str],
) -> list[str]:
    findings: list[str] = []
    if unsupported_claim_ids:
        findings.append(f"{len(unsupported_claim_ids)} profile claims are unsupported")
    if missing_gold_fact_ids:
        findings.append(f"{len(missing_gold_fact_ids)} gold profile facts are missing")
    if missing_critical_paths:
        findings.append(
            f"{len(missing_critical_paths)} critical repository paths were not read or searched"
        )
    if invalid_evidence_refs:
        findings.append(f"{len(invalid_evidence_refs)} evidence refs do not exist in the snapshot")
    if listed_only_evidence_refs:
        findings.append(
            f"{len(listed_only_evidence_refs)} evidence refs were listed but not read or searched"
        )
    if invalid_matched_fact_ids:
        findings.append(
            f"{len(invalid_matched_fact_ids)} claim matches reference unknown gold fact ids"
        )
    return findings
