from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from guidesync_agent.agent_runtime import release_notes
from guidesync_agent.agent_runtime.pydantic_ai import agent_usage, close_model_client
from guidesync_agent.schemas import DocumentationUpdate, EvidenceBundle, ProviderConfig


def valid_update() -> DocumentationUpdate:
    return DocumentationUpdate(
        title="Release title",
        summary="Release summary",
        user_facing_change="Users can review the release.",
        proposed_update_markdown="## Release title\n\nUsers can review the release.",
        evidence_used=[],
        reviewer_checks=[],
    )


def test_release_notes_agent_uses_extra_output_retries(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_pydantic_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output=valid_update(),
            usage={"orchestrator_structured_output_mode": "tool"},
        )

    monkeypatch.setattr(release_notes, "run_pydantic_agent", fake_run_pydantic_agent)

    update, usage = asyncio.run(
        release_notes.run_release_notes_agent(
            goal="Draft release notes.",
            audience="end_users",
            evidence=EvidenceBundle(),
            config=ProviderConfig(),
        )
    )

    assert captured["retries"] == release_notes.RELEASE_NOTES_AGENT_RETRIES
    assert "DocumentationUpdate" in captured["instructions"]
    assert captured["output_model"] is DocumentationUpdate
    assert update.title == "Release title"
    assert usage["prompt_strategy"] == "release_notes_agent_tools"
    assert usage["release_notes_agent_prompt_id"] == "release_notes.agent_instructions"
    assert usage["release_notes_agent_prompt_version"] == "release-notes-agent-v2"
    assert len(usage["release_notes_agent_prompt_sha256"]) == 64
    assert usage["release_notes_agent_structured_output_mode"] == "tool"


def test_close_model_client_closes_async_openai_client() -> None:
    closed = False

    class FakeClient:
        async def close(self) -> None:
            nonlocal closed
            closed = True

    asyncio.run(close_model_client(SimpleNamespace(client=FakeClient())))

    assert closed


def test_agent_usage_prefers_model_dump_without_calling_usage() -> None:
    class CallableUsage:
        def __call__(self) -> None:
            raise AssertionError("deprecated usage() should not be called")

        def model_dump(self) -> dict[str, int]:
            return {"total_tokens": 42}

    result = SimpleNamespace(usage=CallableUsage())

    assert agent_usage(result) == {"total_tokens": 42}


def test_agent_usage_serializes_callable_dataclass_without_calling_usage() -> None:
    @dataclass
    class CallableUsage:
        total_tokens: int

        def __call__(self) -> None:
            raise AssertionError("deprecated usage() should not be called")

    result = SimpleNamespace(usage=CallableUsage(total_tokens=42))

    assert agent_usage(result) == {"total_tokens": 42}
