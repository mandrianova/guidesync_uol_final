from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.test import TestModel
from storage_test_utils import sqlite_database_url

from guidesync_agent.schemas import (
    LLMTranscriptEventKind,
    ModelRole,
    ProviderConfig,
    ProviderKind,
)
from guidesync_agent.services import pydantic_agent_runtime
from guidesync_agent.services.llm_transcripts import read_transcript_artifact


class RuntimeOutput(BaseModel):
    answer: str


@dataclass
class RuntimeDeps:
    tool_calls: int = 0


def test_pydantic_agent_runtime_persists_tool_events_to_db(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = sqlite_database_url(tmp_path / "runtime-transcripts.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setattr(
        pydantic_agent_runtime,
        "build_pydantic_ai_model",
        lambda _config: TestModel(
            call_tools=["echo_tool"],
            custom_output_args={"answer": "done"},
        ),
    )

    def register_tools(agent: Agent[RuntimeDeps, RuntimeOutput]) -> None:
        @agent.tool
        def echo_tool(ctx: RunContext[RuntimeDeps], value: str = "hello") -> dict[str, str]:
            """Echo a value through a deterministic test tool."""
            ctx.deps.tool_calls += 1
            return {"echo": value}

    result = pydantic_agent_runtime.run_pydantic_agent_sync(
        prompt="Use the echo tool and return done.",
        instructions="Call the tool once.",
        output_model=RuntimeOutput,
        deps=RuntimeDeps(),
        deps_type=RuntimeDeps,
        config=ProviderConfig(
            provider=ProviderKind.PYDANTIC_AI,
            model="openai-chat:test-model",
        ),
        model_role=ModelRole.ORCHESTRATOR,
        project_id="project-runtime",
        run_id="run-runtime",
        workflow_task_id="task-runtime",
        register_tools=register_tools,
    )

    loaded = read_transcript_artifact(result.transcript_id or "")

    assert RuntimeOutput.model_validate(result.output).answer == "done"
    assert loaded is not None
    assert loaded.status == "completed"
    event_kinds = [event.event_kind for event in loaded.events]
    assert event_kinds[0] == LLMTranscriptEventKind.MODEL_REQUEST
    assert event_kinds.count(LLMTranscriptEventKind.TOOL_CALL) == 2
    assert event_kinds.count(LLMTranscriptEventKind.TOOL_RESULT) == 2
    assert event_kinds.count(LLMTranscriptEventKind.FINAL_SNAPSHOT) >= 1
    assert loaded.tool_calls[0].name == "echo_tool"
