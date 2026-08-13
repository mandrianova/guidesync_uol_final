from __future__ import annotations

from guidesync_agent.schemas import (
    ChangeAnalysisCheckpoint,
    ChangeAnalysisCoverage,
    ChangeAnalysisCoverageDisposition,
    ChangeAnalysisInventory,
    ChangeAnalysisInventoryItem,
    ReleaseChangeFinding,
)


def covered_keys(checkpoint: ChangeAnalysisCheckpoint) -> set[str]:
    return {
        item.key
        for item in checkpoint.coverage
        if item.disposition
        in {
            ChangeAnalysisCoverageDisposition.FINDING,
            ChangeAnalysisCoverageDisposition.NO_RELEASE_NOTE,
        }
    }


def uncovered_inventory(
    inventory: ChangeAnalysisInventory,
    checkpoint: ChangeAnalysisCheckpoint,
) -> list[ChangeAnalysisInventoryItem]:
    covered = covered_keys(checkpoint)
    return [item for item in inventory.items if item.key not in covered]


def replace_finding(
    checkpoint: ChangeAnalysisCheckpoint,
    finding: ReleaseChangeFinding,
) -> None:
    existing = next(
        (item for item in checkpoint.findings if item.id == finding.id),
        None,
    )
    if existing is not None:
        finding = finding.model_copy(
            update={
                "coverage_keys": _unique_non_empty(
                    [*existing.coverage_keys, *finding.coverage_keys]
                ),
                "evidence_refs": _unique_non_empty(
                    [*existing.evidence_refs, *finding.evidence_refs]
                ),
                "documentation_search_intents": _unique_non_empty(
                    [
                        *existing.documentation_search_intents,
                        *finding.documentation_search_intents,
                    ]
                ),
                "risk_notes": _unique_non_empty(
                    [*existing.risk_notes, *finding.risk_notes]
                ),
                "artifact_ref": finding.artifact_ref or existing.artifact_ref,
            }
        )
    checkpoint.findings = [
        item for item in checkpoint.findings if item.id != finding.id
    ] + [finding]
    checkpoint.coverage = [
        item for item in checkpoint.coverage if item.finding_id != finding.id
    ]
    for key in finding.coverage_keys:
        replace_coverage(
            checkpoint,
            ChangeAnalysisCoverage(
                key=key,
                disposition=ChangeAnalysisCoverageDisposition.FINDING,
                finding_id=finding.id,
                reason=f"Covered by semantic finding {finding.id}",
            ),
        )


def replace_coverage(
    checkpoint: ChangeAnalysisCheckpoint,
    coverage: ChangeAnalysisCoverage,
) -> None:
    checkpoint.coverage = [
        item for item in checkpoint.coverage if item.key != coverage.key
    ] + [coverage]


def _unique_non_empty(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))
