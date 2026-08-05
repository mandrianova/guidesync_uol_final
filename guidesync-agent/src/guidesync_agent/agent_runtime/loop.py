from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel

from guidesync_agent.agent_runtime.context_compaction import ContextCompactionService
from guidesync_agent.schemas import (
    AgentLoopActionType,
    AgentLoopModelAction,
    AgentLoopObservation,
    AgentLoopPromptContext,
    AgentLoopRequest,
    AgentLoopResult,
    AgentLoopToolCall,
)
from guidesync_agent.settings import get_settings


class AgentLoopProvider(Protocol):
    provider: str
    model: str

    def next_action(self, context: AgentLoopPromptContext) -> AgentLoopModelAction: ...


ToolExecutor = Callable[[AgentLoopToolCall], AgentLoopObservation]


def run_agent_loop(
    *,
    request: AgentLoopRequest,
    provider: AgentLoopProvider,
    execute_tool: ToolExecutor,
    final_output_model: type[BaseModel],
    initial_observations: list[AgentLoopObservation] | None = None,
    compaction: ContextCompactionService | None = None,
    emergency_max_steps: int | None = None,
) -> AgentLoopResult:
    started = time.perf_counter()
    all_observations = list(initial_observations or [])
    prompt_observations = list(initial_observations or [])
    checkpoints = []
    actions = []
    compaction = compaction or ContextCompactionService()
    max_steps = emergency_max_steps or get_settings().agent_loop.emergency_max_steps

    for _ in range(max_steps):
        decision = compaction.prepare_prompt_observations(
            request=request,
            observations=prompt_observations,
            checkpoint_count=len(checkpoints),
        )
        prompt_observations = decision.observations
        if decision.checkpoint is not None:
            checkpoints.append(decision.checkpoint)
        context = AgentLoopPromptContext(
            request=request,
            observations=prompt_observations,
            compaction_checkpoints=checkpoints,
            token_estimate=decision.token_estimate,
        )
        action = provider.next_action(context)
        actions.append(action)
        if action.action == AgentLoopActionType.FINAL:
            final_output = final_output_model.model_validate(action.final_output)
            return AgentLoopResult(
                final_output=final_output.model_dump(mode="json"),
                observations=all_observations,
                compaction_checkpoints=checkpoints,
                model_actions=actions,
                provider=provider.provider,
                model=provider.model,
                model_metadata={
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "loop_steps": len(actions),
                    "tool_observations": len(all_observations),
                    "compaction_checkpoints": len(checkpoints),
                    "emergency_max_steps": max_steps,
                },
            )
        if action.tool_call is None:
            raise RuntimeError("agent loop returned tool_call action without tool_call payload")
        observation = execute_tool(action.tool_call)
        all_observations.append(observation)
        prompt_observations.append(observation)

    raise RuntimeError(
        f"agent loop exceeded emergency guard after {max_steps} steps; "
        "this indicates a provider/tool loop bug or an unreachable final response"
    )
