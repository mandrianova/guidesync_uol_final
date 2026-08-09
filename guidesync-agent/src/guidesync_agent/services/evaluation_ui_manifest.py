from __future__ import annotations

from guidesync_agent.schemas import (
    ConditionedUiEvidence,
    ConditionedUiEvidenceItem,
    EvaluationConditionProtocol,
    FrozenUiArtifactManifest,
    FrozenUiEvidenceManifest,
    UiCaptureStatus,
    UiEvidenceModality,
    VersionedUiScenario,
)
from guidesync_agent.services.evaluation_manifest_utils import (
    model_checksum,
    ui_evidence_manifest_checksum,
)


def build_frozen_ui_evidence_manifest(
    scenarios: list[VersionedUiScenario],
    artifacts: list[FrozenUiArtifactManifest],
) -> FrozenUiEvidenceManifest:
    manifest = FrozenUiEvidenceManifest(
        scenarios=scenarios,
        artifacts=artifacts,
    )
    return manifest.model_copy(
        update={"checksum": ui_evidence_manifest_checksum(manifest)}
    )


def validate_ui_evidence_manifest(manifest: FrozenUiEvidenceManifest) -> None:
    expected = ui_evidence_manifest_checksum(manifest)
    if manifest.checksum != expected:
        raise ValueError("UI evidence manifest checksum mismatch")


def apply_ui_evidence_condition(
    manifest: FrozenUiEvidenceManifest,
    protocol: EvaluationConditionProtocol,
) -> ConditionedUiEvidence:
    validate_ui_evidence_manifest(manifest)
    modality = protocol.ui_evidence_modality
    if modality is UiEvidenceModality.NONE:
        return ConditionedUiEvidence(
            modality=modality,
            applied_condition_checksum=model_checksum(protocol),
        )

    items = [
        conditioned_item(artifact, modality)
        for artifact in manifest.artifacts
        if artifact.status is UiCaptureStatus.CAPTURED
    ]
    return ConditionedUiEvidence(
        modality=modality,
        applied_condition_checksum=model_checksum(protocol),
        items=items,
    )


def conditioned_item(
    artifact: FrozenUiArtifactManifest,
    modality: UiEvidenceModality,
) -> ConditionedUiEvidenceItem:
    if artifact.viewport is None or artifact.theme is None:
        raise ValueError("captured UI artifact is missing viewport or theme")
    refs = [
        reference
        for reference in (artifact.dom_artifact_ref, artifact.aria_artifact_ref)
        if reference is not None
    ]
    include_png = modality is UiEvidenceModality.DOM_ARIA_PNG
    if include_png and artifact.png_artifact_ref:
        refs.append(artifact.png_artifact_ref)
    return ConditionedUiEvidenceItem(
        scenario_id=artifact.scenario_id,
        route=artifact.route,
        viewport=artifact.viewport,
        theme=artifact.theme,
        observed_state=artifact.observed_state,
        dom_sha256=artifact.dom_sha256,
        dom_artifact_ref=artifact.dom_artifact_ref,
        aria_sha256=artifact.aria_sha256,
        aria_artifact_ref=artifact.aria_artifact_ref,
        png_sha256=artifact.png_sha256 if include_png else None,
        png_artifact_ref=artifact.png_artifact_ref if include_png else None,
        evidence_refs=refs,
    )
