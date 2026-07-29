from __future__ import annotations

from collections.abc import Iterable

from guidesync_agent.schemas import EvaluationAdjudicationStatus


def is_scorable_gold(status: EvaluationAdjudicationStatus) -> bool:
    return status in {
        EvaluationAdjudicationStatus.SINGLE_ANNOTATOR,
        EvaluationAdjudicationStatus.ADJUDICATED,
    }


def gold_status_findings(
    statuses: Iterable[EvaluationAdjudicationStatus],
    *,
    label: str,
) -> list[str]:
    values = list(statuses)
    single_annotator = values.count(EvaluationAdjudicationStatus.SINGLE_ANNOTATOR)
    drafts = values.count(EvaluationAdjudicationStatus.DRAFT)
    findings: list[str] = []
    if single_annotator:
        findings.append(
            f"{single_annotator} {label} use single-annotator gold and were scored "
            "provisionally"
        )
    if drafts:
        findings.append(f"{drafts} draft {label} were excluded from scoring")
    return findings
