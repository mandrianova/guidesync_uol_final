from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from guidesync_agent import model_smoke
from guidesync_agent.schemas import ModelRole, ModelSmokeRequest, ModelSmokeStatus


def test_model_smoke_dry_run_writes_report(tmp_path: Path) -> None:
    output_path = tmp_path / "model-smoke.json"
    report = asyncio.run(
        model_smoke.run_model_smoke(
            ModelSmokeRequest(
                roles=[ModelRole.CODE_CHANGE_ANALYSIS],
                output_path=output_path,
            )
        )
    )

    assert output_path.exists()
    assert report.results[0].status == ModelSmokeStatus.PLANNED
    assert report.results[0].skipped_reason == "dry run; pass --execute to call the provider"


def test_model_smoke_skips_remote_provider_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("GUIDESYNC_AGENT_PROVIDER", "pydantic_ai")
    monkeypatch.setenv("GUIDESYNC_AGENT_MODEL", "openai:gpt-4.1")
    monkeypatch.setenv("GUIDESYNC_AGENT_BASE_URL", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    report = asyncio.run(
        model_smoke.run_model_smoke(
            ModelSmokeRequest(roles=[ModelRole.ORCHESTRATOR], execute=True)
        )
    )

    assert report.results[0].status == ModelSmokeStatus.SKIPPED
    assert report.results[0].skipped_reason == (
        "missing API key; set OPENAI_API_KEY or configure a saved profile token"
    )


def test_model_smoke_executes_local_http_text_smoke(monkeypatch) -> None:
    monkeypatch.setenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_PROVIDER", "local_http")
    monkeypatch.setenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_MODEL", "openai:local-smoke")
    monkeypatch.setenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_BASE_URL", "http://models.local/v1")

    def fake_post_local_chat(*_args: Any, **_kwargs: Any) -> dict[str, object]:
        return {"choices": [{"message": {"content": "local smoke passed"}}]}

    monkeypatch.setattr(model_smoke, "post_local_chat", fake_post_local_chat)

    report = asyncio.run(
        model_smoke.run_model_smoke(
            ModelSmokeRequest(roles=[ModelRole.CODE_CHANGE_ANALYSIS], execute=True)
        )
    )

    assert report.results[0].status == ModelSmokeStatus.PASSED
    assert report.results[0].response_excerpt == "local smoke passed"
