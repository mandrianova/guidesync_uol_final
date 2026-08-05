from __future__ import annotations

import json
from dataclasses import dataclass

from guidesync_agent.schemas import (
    AgentLoopCompactionCheckpoint,
    AgentLoopObservation,
    AgentLoopRequest,
)
from guidesync_agent.settings import get_settings

DEFAULT_COMPACTION_RATIO = 0.8


@dataclass(frozen=True)
class CompactionDecision:
    observations: list[AgentLoopObservation]
    checkpoint: AgentLoopCompactionCheckpoint | None
    token_estimate: int


class ContextCompactionService:
    def __init__(
        self,
        *,
        context_window_tokens: int | None = None,
        threshold_tokens: int | None = None,
        retain_recent_observations: int | None = None,
    ) -> None:
        settings = get_settings().agent_loop
        self.context_window_tokens = (
            context_window_tokens
            or settings.context_window_tokens
        )
        self.threshold_tokens = (
            threshold_tokens
            or settings.compaction_threshold_tokens
            or int(self.context_window_tokens * DEFAULT_COMPACTION_RATIO)
        )
        self.retain_recent_observations = (
            retain_recent_observations
            if retain_recent_observations is not None
            else settings.retain_recent_observations
        )

    def prepare_prompt_observations(
        self,
        *,
        request: AgentLoopRequest,
        observations: list[AgentLoopObservation],
        checkpoint_count: int,
    ) -> CompactionDecision:
        token_estimate = estimate_tokens(
            {
                "request": request.model_dump(mode="json"),
                "observations": [item.model_dump(mode="json") for item in observations],
                "checkpoint_count": checkpoint_count,
            }
        )
        if token_estimate <= self.threshold_tokens:
            return CompactionDecision(
                observations=observations,
                checkpoint=None,
                token_estimate=token_estimate,
            )

        retained_count = max(1, self.retain_recent_observations)
        if len(observations) <= retained_count:
            return CompactionDecision(
                observations=observations,
                checkpoint=None,
                token_estimate=token_estimate,
            )

        compacted = observations[:-retained_count]
        retained = observations[-retained_count:]
        checkpoint = AgentLoopCompactionCheckpoint(
            summarized_observation_ids=[item.id for item in compacted],
            trigger_token_estimate=token_estimate,
            retained_observation_count=len(retained),
            summary=summarize_observations(compacted),
        )
        return CompactionDecision(
            observations=retained,
            checkpoint=checkpoint,
            token_estimate=token_estimate,
        )


def summarize_observations(observations: list[AgentLoopObservation]) -> str:
    lines = [
        "Compacted earlier agent-loop observations. Full raw observations remain "
        "available in the persisted trace/artifacts and are not repeated in the prompt. "
        "Read-only tool policy, resource scopes, trust labels, denial/error summaries, "
        "evidence refs, and artifact refs are preserved in this checkpoint."
    ]
    for observation in observations:
        status = "ok" if observation.ok else "error"
        evidence = ", ".join(observation.evidence_refs[:5])
        detail = observation.output_summary or observation.error_message or ""
        line = (
            f"- {observation.id}: {observation.tool_name.value} "
            f"[{status}/{observation.result_status.value}; "
            f"trust={observation.trust_level.value}] {detail}"
        )
        if evidence:
            line = f"{line} Evidence refs: {evidence}."
        lines.append(line[:1_000])
    return "\n".join(lines)


def estimate_tokens(value: object) -> int:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        text = str(value)
    return max(1, len(text) // 4)
