from __future__ import annotations

from collections.abc import Callable

from guidesync_agent.schemas import ContextChunk

SUMMARY_PROMPT_VERSION = "context-summary-v1"

SummaryCallable = Callable[[list[ContextChunk]], str]


class EmptySummaryError(RuntimeError):
    pass


class SummarizationService:
    def __init__(
        self,
        summarizer: SummaryCallable | None = None,
        *,
        max_attempts: int = 2,
    ) -> None:
        self.summarizer = summarizer or deterministic_summary
        self.max_attempts = max(1, max_attempts)

    def summarize(self, chunks: list[ContextChunk]) -> tuple[str, dict[str, object]]:
        attempts = 0
        last_summary = ""
        while attempts < self.max_attempts:
            attempts += 1
            last_summary = self.summarizer(chunks).strip()
            if last_summary:
                return last_summary, {"attempts": attempts, "empty_retries": attempts - 1}
        raise EmptySummaryError(
            f"summary response was empty after {attempts} attempts: {last_summary!r}"
        )


def deterministic_summary(chunks: list[ContextChunk]) -> str:
    lines = ["Context summary:"]
    for chunk in chunks:
        preview = " ".join(chunk.text.split())
        if not preview:
            continue
        lines.append(f"- {chunk.id}: {preview[:500]}")
    return "\n".join(lines)
