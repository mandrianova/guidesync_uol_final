from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from guidesync_agent.schemas import (
    EvaluationAdjudicationStatus,
    EvaluationMeasurementStatus,
    FrozenUiArtifactManifest,
    GeneratedClaimSupport,
    ScreenshotAction,
    ScreenshotActionKind,
    ScreenshotLocatorKind,
    ScreenshotTheme,
    ScreenshotViewport,
    UiCaptureChecks,
    UiCaptureStatus,
    UiEvidenceEvaluationInput,
    UiEvidenceGold,
    UiEvidenceModality,
    UiPredictedVisualClaim,
    UiScenarioPrediction,
    UiVisualFactKind,
    UiVisualGoldFact,
    VersionedUiScenario,
)
from guidesync_agent.services.evaluation_conditions import default_condition_protocols
from guidesync_agent.services.evaluation_manifest_utils import model_checksum
from guidesync_agent.services.evaluation_ui_evidence import (
    evaluate_ui_evidence,
    ui_stage_result,
)
from guidesync_agent.services.evaluation_ui_manifest import (
    apply_ui_evidence_condition,
    build_frozen_ui_evidence_manifest,
    validate_ui_evidence_manifest,
)


def test_starlight_head_contract_has_four_bounded_mobile_states() -> None:
    scenarios = starlight_head_scenarios()

    assert len(scenarios) == 4
    assert {
        (scenario.theme, scenario.requested_state) for scenario in scenarios
    } == {
        (ScreenshotTheme.LIGHT, "closed"),
        (ScreenshotTheme.LIGHT, "open"),
        (ScreenshotTheme.DARK, "closed"),
        (ScreenshotTheme.DARK, "open"),
    }
    assert all(
        scenario.viewport == ScreenshotViewport(width=390, height=844)
        for scenario in scenarios
    )
    assert all(
        action.kind in {ScreenshotActionKind.CLICK, ScreenshotActionKind.WAIT_FOR}
        and action.locator_kind is ScreenshotLocatorKind.ROLE
        and action.role_name == "Menu"
        for scenario in scenarios
        for action in scenario.actions
    )


def test_ui_scenario_rejects_raw_scripts_and_unbounded_action_fields() -> None:
    scenario_payload = starlight_head_scenarios()[1].model_dump(mode="json")
    scenario_payload["actions"][0]["script"] = "document.body.remove()"

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        VersionedUiScenario.model_validate(scenario_payload)

    action = ScreenshotAction(
        kind=ScreenshotActionKind.CLICK,
        locator_kind=ScreenshotLocatorKind.ROLE,
        locator="button",
        role_name="Menu",
        route="/unbounded-navigation",
    )
    scenario_payload = starlight_head_scenarios()[1].model_dump(mode="json")
    scenario_payload["actions"] = [action.model_dump(mode="json")]

    with pytest.raises(ValueError, match="navigation or timed waits"):
        VersionedUiScenario.model_validate(scenario_payload)


def test_ui_conditions_change_exactly_the_declared_evidence_boundary() -> None:
    manifest = valid_manifest()
    protocols = {
        protocol.condition.id: protocol
        for protocol in default_condition_protocols(include_baselines=False)
    }

    without_ui = apply_ui_evidence_condition(manifest, protocols["G-S"])
    dom_only = apply_ui_evidence_condition(manifest, protocols["G-SD"])
    full = apply_ui_evidence_condition(manifest, protocols["G"])

    assert without_ui.modality is UiEvidenceModality.NONE
    assert without_ui.items == []
    assert dom_only.modality is UiEvidenceModality.DOM_ARIA
    assert full.modality is UiEvidenceModality.DOM_ARIA_PNG
    assert len(dom_only.items) == len(full.items) == 4
    assert all(item.png_artifact_ref is None for item in dom_only.items)
    assert all(item.png_artifact_ref is not None for item in full.items)
    assert all(
        dom.model_dump(exclude={"png_sha256", "png_artifact_ref", "evidence_refs"})
        == rendered.model_dump(
            exclude={"png_sha256", "png_artifact_ref", "evidence_refs"}
        )
        for dom, rendered in zip(dom_only.items, full.items, strict=True)
    )
    for condition_id, packet in (
        ("G-S", without_ui),
        ("G-SD", dom_only),
        ("G", full),
    ):
        assert packet.applied_condition_checksum == model_checksum(
            protocols[condition_id]
        )


def test_ui_evaluation_rejects_an_unattested_condition_projection() -> None:
    manifest = valid_manifest()
    protocol = condition("G-SD")

    with pytest.raises(ValueError, match="condition checksum"):
        UiEvidenceEvaluationInput(
            case_id="starlight-pr-2727-mobile-menu-v1",
            condition_id="G-SD",
            expected_condition_checksum="wrong-condition",
            manifest=manifest,
            gold=gold_bundle(manifest),
            evidence=apply_ui_evidence_condition(manifest, protocol),
        )


def test_dom_only_condition_rejects_a_hidden_png_reference() -> None:
    packet = apply_ui_evidence_condition(valid_manifest(), condition("G-SD"))
    packet_payload = packet.model_dump(mode="json")
    packet_payload["items"][0]["evidence_refs"].append("s3://hidden.png")

    with pytest.raises(ValueError, match="refs must match"):
        type(packet).model_validate(packet_payload)


def test_ui_evaluation_rejects_gold_for_an_unknown_scenario() -> None:
    manifest = valid_manifest()
    protocol = condition("G")
    gold = gold_bundle(manifest)
    gold = gold.model_copy(
        update={
            "facts": [
                gold.facts[0].model_copy(update={"scenario_id": "unknown-scenario"}),
                *gold.facts[1:],
            ]
        }
    )

    with pytest.raises(ValueError, match="gold facts must reference"):
        UiEvidenceEvaluationInput(
            case_id="starlight-pr-2727-mobile-menu-v1",
            condition_id="G",
            expected_condition_checksum=model_checksum(protocol),
            manifest=manifest,
            gold=gold,
            evidence=apply_ui_evidence_condition(manifest, protocol),
        )


def test_ui_evaluator_reports_count_preserving_acquisition_and_visual_metrics() -> None:
    manifest = valid_manifest()
    protocol = condition("G")
    report = evaluate_ui_evidence(
        UiEvidenceEvaluationInput(
            case_id="starlight-pr-2727-mobile-menu-v1",
            condition_id="G",
            expected_condition_checksum=model_checksum(protocol),
            manifest=manifest,
            gold=gold_bundle(manifest),
            evidence=apply_ui_evidence_condition(manifest, protocol),
            predictions=correct_predictions(manifest, protocol),
        )
    )

    assert report.acquisition_status is EvaluationMeasurementStatus.MEASURED
    assert report.interpretation_status is EvaluationMeasurementStatus.MEASURED
    assert report.acquisition_counts.requested == 4
    assert report.acquisition_counts.valid == 4
    assert report.claim_counts.total == 4
    assert report.claim_counts.supported == 4
    assert metric(report.health_metrics, "scenario_coverage").numerator == 4
    assert metric(report.health_metrics, "scenario_coverage").denominator == 4
    assert metric(report.quality_metrics, "visual_fact_precision").value == 1
    assert metric(report.quality_metrics, "visual_fact_recall").value == 1
    assert metric(report.quality_metrics, "visual_fact_f1").value == 1
    assert metric(report.quality_metrics, "state_classification_accuracy").value == 1
    assert metric(report.quality_metrics, "evidence_coverage").value == 1
    stage = ui_stage_result(report, run_id="run-1")
    assert stage.stage.value == "ui_evidence"
    assert stage.status is EvaluationMeasurementStatus.MEASURED


@pytest.mark.parametrize(
    ("field", "value", "count_field"),
    [
        ("route", "/wrong/", "wrong_route"),
        ("viewport", ScreenshotViewport(width=800, height=844), "wrong_viewport"),
        ("theme", ScreenshotTheme.DARK, "wrong_theme"),
        ("observed_state", "wrong", "wrong_state"),
        ("build_identity", "wrong-build", "wrong_build"),
        ("blank", True, "blank"),
    ],
)
def test_invalid_capture_fails_acquisition_without_becoming_visual_error(
    field: str,
    value: object,
    count_field: str,
) -> None:
    manifest = valid_manifest()
    scenario_id = manifest.scenarios[0].id
    artifacts = [
        artifact.model_copy(update={field: value})
        if artifact.scenario_id == scenario_id
        else artifact
        for artifact in manifest.artifacts
    ]
    invalid_manifest = build_frozen_ui_evidence_manifest(
        manifest.scenarios,
        artifacts,
    )
    protocol = condition("G")

    report = evaluate_ui_evidence(
        UiEvidenceEvaluationInput(
            case_id="starlight-pr-2727-mobile-menu-v1",
            condition_id="G",
            expected_condition_checksum=model_checksum(protocol),
            manifest=invalid_manifest,
            gold=gold_bundle(invalid_manifest),
            evidence=apply_ui_evidence_condition(invalid_manifest, protocol),
            predictions=correct_predictions(invalid_manifest, protocol),
        )
    )

    assert report.acquisition_status is EvaluationMeasurementStatus.FAILED
    assert getattr(report.acquisition_counts, count_field) == 1
    assert report.invalid_scenario_ids == [scenario_id]
    assert report.unevaluated_prediction_ids == [scenario_id]
    assert report.claim_counts.total == 3
    assert report.claim_counts.supported == 3
    assert metric(report.quality_metrics, "visual_fact_precision").value == 1


def test_no_ui_condition_marks_intrinsic_metrics_not_evaluated() -> None:
    manifest = valid_manifest()
    protocol = condition("G-S")
    report = evaluate_ui_evidence(
        UiEvidenceEvaluationInput(
            case_id="starlight-pr-2727-mobile-menu-v1",
            condition_id="G-S",
            expected_condition_checksum=model_checksum(protocol),
            manifest=manifest,
            gold=gold_bundle(manifest),
            evidence=apply_ui_evidence_condition(manifest, protocol),
        )
    )

    assert report.acquisition_status is EvaluationMeasurementStatus.MEASURED
    assert report.interpretation_status is EvaluationMeasurementStatus.NOT_EVALUATED
    assert all(
        item.status is EvaluationMeasurementStatus.NOT_EVALUATED
        for item in report.quality_metrics
    )


def test_ui_evaluator_retains_entailment_counts_and_invalid_refs() -> None:
    manifest = valid_manifest()
    protocol = condition("G-SD")
    packet = apply_ui_evidence_condition(manifest, protocol)
    scenario = manifest.scenarios[0]
    predictions = [
        UiScenarioPrediction(
            scenario_id=scenario.id,
            predicted_state=scenario.requested_state,
            claims=[
                UiPredictedVisualClaim(
                    id="supported",
                    statement="The expected icon is visible.",
                    support=GeneratedClaimSupport.SUPPORTED,
                    matched_gold_fact_ids=[f"fact-{scenario.id}"],
                    evidence_refs=[packet.items[0].dom_artifact_ref or ""],
                ),
                UiPredictedVisualClaim(
                    id="contradicted",
                    statement="A different icon is visible.",
                    support=GeneratedClaimSupport.CONTRADICTED,
                    evidence_refs=["artifact:png-not-in-dom-condition"],
                ),
                UiPredictedVisualClaim(
                    id="unknown",
                    statement="The color has a specific perceptual quality.",
                    support=GeneratedClaimSupport.NOT_ENOUGH_EVIDENCE,
                ),
            ],
        )
    ]
    report = evaluate_ui_evidence(
        UiEvidenceEvaluationInput(
            case_id="starlight-pr-2727-mobile-menu-v1",
            condition_id="G-SD",
            expected_condition_checksum=model_checksum(protocol),
            manifest=manifest,
            gold=gold_bundle(manifest),
            evidence=packet,
            predictions=predictions,
        )
    )

    assert report.claim_counts.supported == 1
    assert report.claim_counts.contradicted == 1
    assert report.claim_counts.not_enough_evidence == 1
    assert report.contradicted_claim_ids == ["contradicted"]
    assert report.not_enough_evidence_claim_ids == ["unknown"]
    assert report.invalid_evidence_refs == ["artifact:png-not-in-dom-condition"]
    assert metric(report.quality_metrics, "unsupported_visual_claim_rate").numerator == 2
    assert metric(report.quality_metrics, "unsupported_visual_claim_rate").denominator == 3


def test_ui_manifest_checksum_drift_is_rejected() -> None:
    manifest = valid_manifest()
    drifted = manifest.model_copy(
        update={
            "artifacts": [
                manifest.artifacts[0].model_copy(update={"route": "/drifted/"}),
                *manifest.artifacts[1:],
            ]
        }
    )

    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_ui_evidence_manifest(drifted)


def valid_manifest():
    scenarios = starlight_head_scenarios()
    artifacts = [artifact_for(scenario) for scenario in scenarios]
    return build_frozen_ui_evidence_manifest(scenarios, artifacts)


def starlight_head_scenarios() -> list[VersionedUiScenario]:
    scenarios: list[VersionedUiScenario] = []
    viewport = ScreenshotViewport(width=390, height=844)
    for theme in (ScreenshotTheme.LIGHT, ScreenshotTheme.DARK):
        for state in ("closed", "open"):
            actions = []
            if state == "open":
                actions = [
                    ScreenshotAction(
                        kind=ScreenshotActionKind.CLICK,
                        locator_kind=ScreenshotLocatorKind.ROLE,
                        locator="button",
                        role_name="Menu",
                    ),
                    ScreenshotAction(
                        kind=ScreenshotActionKind.WAIT_FOR,
                        locator_kind=ScreenshotLocatorKind.ROLE,
                        locator="button",
                        role_name="Menu",
                    ),
                ]
            scenario_id = f"head-{theme.value}-{state}"
            scenarios.append(
                VersionedUiScenario(
                    id=scenario_id,
                    build_identity="starlight-synthetic-head",
                    route="/getting-started/",
                    viewport=viewport,
                    theme=theme,
                    requested_state=state,
                    actions=actions,
                    checks=UiCaptureChecks(
                        route="/getting-started/",
                        viewport=viewport,
                        theme=theme,
                        state=state,
                    ),
                    evidence_refs=["repo:packages/starlight/components/MobileMenuToggle.astro"],
                )
            )
    return scenarios


def artifact_for(scenario: VersionedUiScenario) -> FrozenUiArtifactManifest:
    return FrozenUiArtifactManifest(
        scenario_id=scenario.id,
        status=UiCaptureStatus.CAPTURED,
        route=scenario.route,
        viewport=scenario.viewport,
        theme=scenario.theme,
        observed_state=scenario.requested_state,
        browser_identity="chromium@sha256:browser-image",
        build_identity=scenario.build_identity,
        png_sha256=digest(f"{scenario.id}:png"),
        png_artifact_ref=f"s3:evaluation/{scenario.id}.png",
        dom_sha256=digest(f"{scenario.id}:dom"),
        dom_artifact_ref=f"s3:evaluation/{scenario.id}.dom.html",
        aria_sha256=digest(f"{scenario.id}:aria"),
        aria_artifact_ref=f"s3:evaluation/{scenario.id}.aria.yml",
        captured_at=datetime(2026, 8, 9, 8, 0, tzinfo=UTC),
    )


def gold_bundle(manifest) -> UiEvidenceGold:
    return UiEvidenceGold(
        case_id="starlight-pr-2727-mobile-menu-v1",
        version="starlight-ui-v1",
        facts=[
            UiVisualGoldFact(
                id=f"fact-{scenario.id}",
                scenario_id=scenario.id,
                kind=UiVisualFactKind.ICON_STATE,
                statement=f"The menu control is {scenario.requested_state}.",
                evidence_refs=[f"s3:evaluation/{scenario.id}.png"],
                adjudication_status=EvaluationAdjudicationStatus.ADJUDICATED,
            )
            for scenario in manifest.scenarios
        ],
    )


def correct_predictions(manifest, protocol) -> list[UiScenarioPrediction]:
    packet = apply_ui_evidence_condition(manifest, protocol)
    refs = {item.scenario_id: item.evidence_refs for item in packet.items}
    return [
        UiScenarioPrediction(
            scenario_id=scenario.id,
            predicted_state=scenario.requested_state,
            claims=[
                UiPredictedVisualClaim(
                    id=f"claim-{scenario.id}",
                    statement=f"The menu control is {scenario.requested_state}.",
                    support=GeneratedClaimSupport.SUPPORTED,
                    matched_gold_fact_ids=[f"fact-{scenario.id}"],
                    evidence_refs=[refs[scenario.id][0]],
                )
            ],
        )
        for scenario in manifest.scenarios
    ]


def condition(condition_id: str):
    return next(
        protocol
        for protocol in default_condition_protocols(include_baselines=False)
        if protocol.condition.id == condition_id
    )


def metric(metrics, name: str):
    return next(item for item in metrics if item.name == name)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
