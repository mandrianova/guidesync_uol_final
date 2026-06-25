from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

from guidesync_agent.schemas import (
    ContextBudgetResult,
    ContextChunk,
    ContextSummaryArtifact,
    ValidationFinding,
)
from guidesync_agent.services.summarization import (
    SUMMARY_PROMPT_VERSION,
    EmptySummaryError,
    SummarizationService,
)

TOKEN_CHAR_RATIO = 4
DEFAULT_CONTEXT_SUMMARY_DIR = Path("outputs/context-summaries")

T = TypeVar("T")
ContextCallable = Callable[[list[ContextChunk]], Awaitable[T]]


class ContextBudgetService:
    def __init__(
        self,
        *,
        token_budget: int,
        output_dir: Path | None = None,
        summarization: SummarizationService | None = None,
    ) -> None:
        self.token_budget = token_budget
        self.output_dir = output_dir or DEFAULT_CONTEXT_SUMMARY_DIR
        self.summarization = summarization or SummarizationService()

    def token_estimate(self, text: str) -> int:
        return max(1, (len(text) + TOKEN_CHAR_RATIO - 1) // TOKEN_CHAR_RATIO)

    def chunks_token_estimate(self, chunks: list[ContextChunk]) -> int:
        return sum(self.token_estimate(chunk.text) for chunk in chunks)

    def compact_if_needed(self, chunks: list[ContextChunk]) -> ContextBudgetResult:
        total = self.chunks_token_estimate(chunks)
        if total <= self.token_budget:
            return ContextBudgetResult(chunks=chunks, token_estimate=total)

        retained = [chunk for chunk in chunks if chunk.retain]
        summarized = [chunk for chunk in chunks if not chunk.retain]
        if not summarized:
            return ContextBudgetResult(
                chunks=chunks,
                token_estimate=total,
                findings=[
                    ValidationFinding(
                        severity="warning",
                        check="context-budget",
                        message="Context exceeds budget but all chunks were marked retain.",
                    )
                ],
            )

        try:
            summary, diagnostics = self.summarization.summarize(summarized)
        except EmptySummaryError as exc:
            return ContextBudgetResult(
                chunks=chunks,
                token_estimate=total,
                findings=[
                    ValidationFinding(
                        severity="error",
                        check="context-summary",
                        message=str(exc),
                    )
                ],
            )

        summary_chunk = ContextChunk(
            id="context-summary",
            role="summary",
            text=summary,
            retain=True,
            metadata={"prompt_version": SUMMARY_PROMPT_VERSION},
        )
        next_chunks = [*retained, summary_chunk]
        artifact = self.write_summary_artifact(
            original_chunks=summarized,
            summary_chunk=summary_chunk,
            original_token_estimate=total,
            diagnostics=diagnostics,
        )
        return ContextBudgetResult(
            chunks=next_chunks,
            artifact=artifact,
            findings=[],
            token_estimate=self.chunks_token_estimate(next_chunks),
        )

    async def with_context_retry(
        self,
        chunks: list[ContextChunk],
        call: ContextCallable[T],
    ) -> tuple[T, ContextBudgetResult | None]:
        try:
            return await call(chunks), None
        except Exception as exc:
            if not is_context_length_error(exc):
                raise
            compacted = self.compact_if_needed(chunks)
            if compacted.artifact is None:
                raise
            return await call(compacted.chunks), compacted

    def write_summary_artifact(
        self,
        *,
        original_chunks: list[ContextChunk],
        summary_chunk: ContextChunk,
        original_token_estimate: int,
        diagnostics: dict[str, object],
    ) -> ContextSummaryArtifact:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = self.output_dir / f"{summary_chunk.id}.json"
        artifact = ContextSummaryArtifact(
            path=str(artifact_path),
            prompt_version=SUMMARY_PROMPT_VERSION,
            original_chunk_ids=[chunk.id for chunk in original_chunks],
            summary_chunk_id=summary_chunk.id,
            original_token_estimate=original_token_estimate,
            summary_token_estimate=self.token_estimate(summary_chunk.text),
            diagnostics=diagnostics,
        )
        artifact_path.write_text(
            json.dumps(
                {
                    "artifact": artifact.model_dump(mode="json"),
                    "summary": summary_chunk.model_dump(mode="json"),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return artifact


def is_context_length_error(exc: Exception) -> bool:
    detail = str(exc).lower()
    markers = [
        "context length",
        "context window",
        "maximum context",
        "too many tokens",
        "n_keep",
    ]
    return any(marker in detail for marker in markers)
