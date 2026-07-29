from __future__ import annotations

import json
from pathlib import Path

from guidesync_agent.schemas import EvaluationGoldBundle, PipelineEvaluationScorecard


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
