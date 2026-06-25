from __future__ import annotations

import asyncio
import json
from pathlib import Path

from guidesync_agent.schemas import ContextChunk
from guidesync_agent.services.context_budget import ContextBudgetService
from guidesync_agent.services.summarization import SummarizationService


def test_budget_below_threshold_does_not_summarize(tmp_path: Path) -> None:
    service = ContextBudgetService(token_budget=100, output_dir=tmp_path)
    chunks = [ContextChunk(id="goal", text="short context", retain=True)]

    result = service.compact_if_needed(chunks)

    assert result.chunks == chunks
    assert result.artifact is None
    assert result.findings == []


def test_budget_above_threshold_writes_summary_artifact(tmp_path: Path) -> None:
    service = ContextBudgetService(token_budget=20, output_dir=tmp_path)
    chunks = [
        ContextChunk(id="instructions", text="Keep this instruction.", retain=True),
        ContextChunk(id="diff", text="changed file " * 200),
    ]

    result = service.compact_if_needed(chunks)

    assert result.artifact is not None
    assert result.chunks[0].id == "instructions"
    assert result.chunks[1].id == "context-summary"
    assert result.artifact.original_chunk_ids == ["diff"]
    artifact_payload = json.loads(Path(result.artifact.path).read_text(encoding="utf-8"))
    assert artifact_payload["artifact"]["prompt_version"] == "context-summary-v1"
    assert artifact_payload["summary"]["metadata"]["prompt_version"] == "context-summary-v1"


def test_empty_summary_response_causes_retry_and_finding(tmp_path: Path) -> None:
    calls = 0

    def empty_summarizer(_: list[ContextChunk]) -> str:
        nonlocal calls
        calls += 1
        return ""

    service = ContextBudgetService(
        token_budget=1,
        output_dir=tmp_path,
        summarization=SummarizationService(empty_summarizer, max_attempts=2),
    )

    result = service.compact_if_needed([ContextChunk(id="diff", text="large context" * 100)])

    assert calls == 2
    assert result.artifact is None
    assert result.findings
    assert result.findings[0].check == "context-summary"


def test_context_length_error_triggers_summary_and_retry(tmp_path: Path) -> None:
    service = ContextBudgetService(token_budget=5, output_dir=tmp_path)
    chunks = [ContextChunk(id="diff", text="large context " * 100)]
    calls = 0

    async def call_provider(next_chunks: list[ContextChunk]) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("context length exceeded")
        assert next_chunks[0].id == "context-summary"
        return "ok"

    result, compacted = asyncio.run(service.with_context_retry(chunks, call_provider))

    assert result == "ok"
    assert calls == 2
    assert compacted is not None
    assert compacted.artifact is not None
