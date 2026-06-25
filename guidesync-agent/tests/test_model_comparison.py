from __future__ import annotations

import asyncio
import json
from pathlib import Path

from guidesync_agent.schemas import (
    GuideSyncRunRequest,
    ModelComparisonRequest,
    ProviderConfig,
    ProviderKind,
    RepositoryInput,
)
from guidesync_agent.workflows.model_comparison import run_model_comparison


def test_model_comparison_runs_share_input_bundle(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "GUIDESYNC_DATABASE_URL",
        f"sqlite+pysqlite:///{tmp_path / 'comparison.db'}",
    )
    request = ModelComparisonRequest(
        name="Local vs API fixture",
        base_request=GuideSyncRunRequest(
            goal="Compare model outputs for documentation.",
            repositories=[RepositoryInput(name="fixture", path=Path("."))],
        ),
        providers=[
            ProviderConfig(provider=ProviderKind.MOCK, model="mock:local"),
            ProviderConfig(provider=ProviderKind.MOCK, model="mock:api"),
        ],
    )

    report = asyncio.run(run_model_comparison(request, tmp_path))

    assert len(report.runs) == 2
    assert {run.input_bundle_id for run in report.runs} == {report.input_bundle_id}


def test_model_comparison_report_includes_models_prompts_and_latency(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "GUIDESYNC_DATABASE_URL",
        f"sqlite+pysqlite:///{tmp_path / 'comparison-report.db'}",
    )
    request = ModelComparisonRequest(
        name="Comparison report fixture",
        base_request=GuideSyncRunRequest(
            goal="Compare model report metadata.",
            repositories=[RepositoryInput(name="fixture", path=Path("."))],
        ),
        providers=[
            ProviderConfig(provider=ProviderKind.MOCK, model="mock:local"),
            ProviderConfig(provider=ProviderKind.MOCK, model="mock:api"),
        ],
        input_bundle_id="input-fixed",
    )

    report = asyncio.run(run_model_comparison(request, tmp_path))

    markdown = (tmp_path / "model-comparison.md").read_text(encoding="utf-8")
    payload = json.loads((tmp_path / "model-comparison.json").read_text(encoding="utf-8"))

    assert report.artifacts["model-comparison.md"]
    assert "mock:local" in markdown
    assert "mock:api" in markdown
    assert "Prompt versions" in markdown
    assert "Latency" in markdown
    assert payload["input_bundle_id"] == "input-fixed"
    assert {run["model"] for run in payload["runs"]} == {"mock:local", "mock:api"}
