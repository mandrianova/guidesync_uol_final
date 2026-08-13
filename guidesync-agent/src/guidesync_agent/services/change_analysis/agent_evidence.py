from __future__ import annotations

from guidesync_agent.schemas import (
    AgentLoopObservation,
    CodeChangeEvidenceRef,
)


def code_change_evidence_refs_from_observations(
    observations: list[AgentLoopObservation],
    seed_refs: list[CodeChangeEvidenceRef],
) -> list[CodeChangeEvidenceRef]:
    refs = {ref.source: ref for ref in seed_refs}
    for observation in observations:
        for source in observation.evidence_refs:
            refs.setdefault(
                source,
                CodeChangeEvidenceRef(
                    source=source,
                    detail=observation.output_summary,
                    artifact_ref=observation.artifact_ref,
                ),
            )
    return list(refs.values())


def combined_evidence_refs(
    left: list[CodeChangeEvidenceRef],
    right: list[CodeChangeEvidenceRef],
) -> list[CodeChangeEvidenceRef]:
    refs = {ref.source: ref for ref in left}
    refs.update({ref.source: ref for ref in right})
    return list(refs.values())
