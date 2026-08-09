from __future__ import annotations

import json
from pathlib import Path

import pytest

from guidesync_agent.schemas import (
    EvaluationGoldBundle,
    PipelineEvaluationScorecard,
    UiEvidenceGold,
    UiVisualFactKind,
    UiVisualGoldFact,
)


def test_fastapi_pilot_gold_bundle_is_valid() -> None:
    draft_report_root = Path("/draft-report")
    if not draft_report_root.exists():
        draft_report_root = Path(__file__).parents[3] / "draft-report"
    path = (
        draft_report_root
        / "evaluation"
        / "fastapi-pr-15022"
        / "GOLD_LABELS.json"
    )

    gold = EvaluationGoldBundle.model_validate(json.loads(path.read_text()))

    assert gold.case_id == "fastapi-pr-15022"
    assert gold.knowledge_corpus.expected_discovered == 389
    assert gold.knowledge_corpus.expected_supported == 149
    assert gold.knowledge_corpus.expected_indexed == 148
    assert len(gold.change_impact.files) == 13
    assert sum(len(file.obligations) for file in gold.change_impact.files) == 6
    assert sum(
        {"critical": 3, "major": 2, "minor": 1}[obligation.severity.value]
        for file in gold.change_impact.files
        for obligation in file.obligations
    ) == 14


def test_fastapi_upstream_scorecard_uses_the_runtime_contract() -> None:
    draft_report_root = Path("/draft-report")
    if not draft_report_root.exists():
        draft_report_root = Path(__file__).parents[3] / "draft-report"
    payload = json.loads(
        (
            draft_report_root
            / "evaluation"
            / "fastapi-pr-15022"
            / "UPSTREAM_STAGE_SCORECARD.json"
        ).read_text()
    )

    scorecard = PipelineEvaluationScorecard.model_validate(
        payload["pipeline_scorecard"]
    )

    assert scorecard.case_id == "fastapi-pr-15022"
    assert [result.stage.value for result in scorecard.stage_results] == [
        "project_profile",
        "knowledge_index",
        "nlp_annotation",
        "retrieval",
    ]

    ablation = PipelineEvaluationScorecard.model_validate(
        json.loads(
            (
                draft_report_root
                / "evaluation"
                / "fastapi-pr-15022"
                / "UPSTREAM_NO_ANNOTATION_SCORECARD.json"
            ).read_text()
        )
    )

    assert ablation.condition.id == "U-GA"
    assert ablation.condition.config_checksum
    assert ablation.stage_results[-1].quality_metrics[0].value == 0.7

    failed_full = PipelineEvaluationScorecard.model_validate_json(
        (
            draft_report_root
            / "evaluation"
            / "fastapi-pr-15022"
            / "CURRENT_FULL_RUN_SCORECARD.json"
        ).read_text()
    )

    assert failed_full.condition.id == "G"
    assert failed_full.stage_results[-1].stage.value == "end_to_end"
    assert failed_full.stage_results[-1].quality_metrics[0].value == 0.0


def test_gold_bundle_requires_bidirectional_visual_obligation_links() -> None:
    draft_report_root = Path("/draft-report")
    if not draft_report_root.exists():
        draft_report_root = Path(__file__).parents[3] / "draft-report"
    gold = EvaluationGoldBundle.model_validate_json(
        (
            draft_report_root
            / "evaluation"
            / "fastapi-pr-15022"
            / "GOLD_LABELS.json"
        ).read_text()
    )
    first_file = gold.change_impact.files[0]
    obligation = first_file.obligations[0].model_copy(
        update={"visual_fact_ids": ["ui-fact-1"]}
    )
    change_impact = gold.change_impact.model_copy(
        update={
            "files": [
                first_file.model_copy(
                    update={"obligations": [obligation, *first_file.obligations[1:]]}
                ),
                *gold.change_impact.files[1:],
            ]
        }
    )
    fact = UiVisualGoldFact(
        id="ui-fact-1",
        scenario_id="scenario-1",
        kind=UiVisualFactKind.ICON_STATE,
        statement="The open state displays a close icon.",
        evidence_refs=["artifact:scenario-1.png"],
        obligation_ids=[obligation.id],
        adjudication_status=gold.adjudication_status,
    )
    payload = gold.model_copy(
        update={
            "change_impact": change_impact,
            "ui_evidence": UiEvidenceGold(
                case_id=gold.case_id,
                version=gold.version,
                facts=[fact],
            ),
        }
    ).model_dump(mode="json")

    linked = EvaluationGoldBundle.model_validate(payload)

    assert linked.ui_evidence is not None
    assert linked.ui_evidence.facts[0].obligation_ids == [obligation.id]

    payload["ui_evidence"]["facts"][0]["obligation_ids"] = []
    with pytest.raises(ValueError, match="bidirectional"):
        EvaluationGoldBundle.model_validate(payload)
