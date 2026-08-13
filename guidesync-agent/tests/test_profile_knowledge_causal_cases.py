from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from guidesync_agent.services.knowledge.synthesis_pilot import (
    PilotCondition,
    failed_pilot_scorecard,
)

FIXTURE = Path("fixtures/evaluation/profile-knowledge-causal-cases.json")


def test_profile_knowledge_cases_are_prospective_and_checksummed() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert payload["prepared_before_outputs"] is True
    assert set(payload["conditions"]) == {"G", "G-P", "G-K", "B3"}
    assert {case["group"] for case in payload["cases"]} == {
        "profile-specific-disambiguation",
        "kb-dependent-stale-guide",
        "synonym-terminology-bridge",
        "negative-internal-change",
    }
    for case in payload["cases"]:
        assert set(case["frozen_inputs"]) == set(case["input_checksums"])
        for name, value in case["frozen_inputs"].items():
            checksum = hashlib.sha256(value.encode("utf-8")).hexdigest()
            assert case["input_checksums"][name] == checksum
        assert set(case["allowed_sources"]) == {"G", "G-P", "G-K", "B3"}
        assert case["gold"]["forbidden_claims"]


def test_no_knowledge_conditions_withhold_every_knowledge_source() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    for case in payload["cases"]:
        assert "knowledge" not in case["allowed_sources"]["G-K"]
        assert "knowledge" not in case["allowed_sources"]["B3"]
        assert "profile" in case["allowed_sources"]["G-K"]
        assert case["allowed_sources"]["B3"] == ["diff"]


def test_failed_pilot_scorecard_is_explicitly_unscored() -> None:
    scorecard = failed_pilot_scorecard(
        "source-run",
        PilotCondition(id="G-K-SYN", knowledge_base=False),
        1,
        RuntimeError("bounded failure"),
        datetime.now(UTC),
    )

    assert scorecard["operational_status"] == "failed"
    assert scorecard["quality_measurement_status"] == "not_evaluated"
    assert scorecard["raw_counts"] is None
    runtime = scorecard["runtime"]
    assert isinstance(runtime, dict)
    assert cast(dict[str, object], runtime)["error"] == "bounded failure"
