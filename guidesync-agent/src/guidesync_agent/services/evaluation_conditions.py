from __future__ import annotations

from guidesync_agent.schemas import (
    EvaluationCondition,
    EvaluationConditionKind,
    EvaluationConditionProtocol,
    PipelineStage,
    UiEvidenceModality,
)
from guidesync_agent.services.evaluation_manifest_utils import (
    condition_protocol_checksum,
)


def default_condition_protocols(
    *,
    include_baselines: bool = True,
) -> list[EvaluationConditionProtocol]:
    protocols = [
        condition_protocol(
            condition_id="G",
            kind=EvaluationConditionKind.FULL,
            label="Full GuideSync",
            behavior="Run every GuideSync stage with the frozen inputs.",
        ),
        ablation_protocol(
            "G-P",
            "Without generated project profile",
            PipelineStage.PROJECT_PROFILE,
            "Use project settings and the repository map only; omit the generated "
            "profile brief and categories.",
        ),
        ablation_protocol(
            "G-A",
            "Without NLP annotations",
            PipelineStage.NLP_ANNOTATION,
            "Keep identical documents, chunks, and embeddings; remove taxonomy, "
            "annotation, and graph ranking signals.",
        ),
        ablation_protocol(
            "G-R",
            "Without existing-document retrieval",
            PipelineStage.RETRIEVAL,
            "Provide an empty existing-document context pack while preserving the "
            "profile and frozen raw change evidence.",
        ),
        ablation_protocol(
            "G-C",
            "Without persisted change analysis",
            PipelineStage.CHANGE_ANALYSIS,
            "Pass the same frozen raw diff and test evidence directly to the "
            "downstream agent instead of persisted file summaries.",
        ),
        ablation_protocol(
            "G-S",
            "Without UI evidence",
            PipelineStage.UI_EVIDENCE,
            "Preserve repository and documentation evidence but provide no PNG or "
            "DOM/ARIA UI evidence.",
            ui_evidence_modality=UiEvidenceModality.NONE,
        ),
        ablation_protocol(
            "G-SD",
            "DOM/ARIA UI evidence only",
            PipelineStage.UI_EVIDENCE,
            "Provide the same frozen DOM/ARIA state evidence but omit PNG and "
            "model-vision input.",
            ui_evidence_modality=UiEvidenceModality.DOM_ARIA,
        ),
        ablation_protocol(
            "G-L",
            "Without separate edit planning",
            PipelineStage.EDIT_PLANNING,
            "Let the documentation agent select targets and write directly from "
            "the otherwise identical evidence bundle.",
        ),
        ablation_protocol(
            "G-V",
            "Without validation",
            PipelineStage.VALIDATION,
            "Preserve and score the pre-validation output; bypass validator "
            "findings and the publishability gate.",
        ),
        ablation_protocol(
            "G-X",
            "Without post-edit reindex",
            PipelineStage.POST_EDIT_REINDEX,
            "Preserve the documentation edit but skip knowledge refresh and score "
            "the next frozen retrieval queries against the stale index.",
        ),
    ]
    if include_baselines:
        protocols.extend(default_baseline_protocols())
    return protocols


def default_baseline_protocols() -> list[EvaluationConditionProtocol]:
    return [
        condition_protocol(
            condition_id="B0",
            kind=EvaluationConditionKind.BASELINE,
            label="Existing stale documentation",
            behavior="Make no documentation update and score the frozen base documents.",
            changed_stages=[
                PipelineStage.CHANGE_ANALYSIS,
                PipelineStage.EDIT_PLANNING,
                PipelineStage.DOCUMENTATION_GENERATION,
                PipelineStage.VALIDATION,
                PipelineStage.POST_EDIT_REINDEX,
            ],
        ),
        condition_protocol(
            condition_id="B1",
            kind=EvaluationConditionKind.BASELINE,
            label="Commit-message rule template",
            behavior="Generate a fixed rule-template update from commit messages only.",
            changed_stages=[
                PipelineStage.PROJECT_PROFILE,
                PipelineStage.NLP_ANNOTATION,
                PipelineStage.RETRIEVAL,
                PipelineStage.CHANGE_ANALYSIS,
                PipelineStage.EDIT_PLANNING,
                PipelineStage.DOCUMENTATION_GENERATION,
            ],
        ),
        condition_protocol(
            condition_id="B2",
            kind=EvaluationConditionKind.BASELINE,
            label="Text-only LLM",
            behavior="Give the same model the PR description and base documents but "
            "withhold code and test diffs.",
            changed_stages=[
                PipelineStage.CHANGE_ANALYSIS,
                PipelineStage.DOCUMENTATION_GENERATION,
            ],
        ),
        condition_protocol(
            condition_id="B3",
            kind=EvaluationConditionKind.BASELINE,
            label="Code-only LLM",
            behavior="Give the same model the code and test diff without knowledge "
            "retrieval or a separate edit planner.",
            changed_stages=[
                PipelineStage.RETRIEVAL,
                PipelineStage.EDIT_PLANNING,
            ],
        ),
    ]


def condition_protocol(  # noqa: PLR0913 - explicit immutable manifest builder
    *,
    condition_id: str,
    kind: EvaluationConditionKind,
    label: str,
    behavior: str,
    changed_stages: list[PipelineStage] | None = None,
    removed_stage: PipelineStage | None = None,
    ui_evidence_modality: UiEvidenceModality = UiEvidenceModality.DOM_ARIA_PNG,
) -> EvaluationConditionProtocol:
    protocol = EvaluationConditionProtocol(
        condition=EvaluationCondition(
            id=condition_id,
            kind=kind,
            label=label,
            removed_stage=removed_stage,
            replacement=behavior if kind == EvaluationConditionKind.ABLATION else None,
        ),
        behavior=behavior,
        changed_stages=changed_stages or [],
        ui_evidence_modality=ui_evidence_modality,
    )
    checksum = condition_protocol_checksum(protocol)
    return protocol.model_copy(
        update={
            "condition": protocol.condition.model_copy(
                update={"config_checksum": checksum}
            )
        }
    )


def ablation_protocol(
    condition_id: str,
    label: str,
    removed_stage: PipelineStage,
    behavior: str,
    *,
    ui_evidence_modality: UiEvidenceModality = UiEvidenceModality.DOM_ARIA_PNG,
) -> EvaluationConditionProtocol:
    return condition_protocol(
        condition_id=condition_id,
        kind=EvaluationConditionKind.ABLATION,
        label=label,
        behavior=behavior,
        changed_stages=[removed_stage],
        removed_stage=removed_stage,
        ui_evidence_modality=ui_evidence_modality,
    )
