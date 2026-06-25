from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from guidesync_agent.agent_runtime import release_notes
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

    class FakeAgent:
        @classmethod
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, *args, **kwargs) -> None:
            captured["retries"] = kwargs["retries"]
            captured["instructions"] = kwargs["instructions"]

        def tool(self, func):
            return func

        async def run(self, prompt, *, deps):
            captured["prompt"] = prompt
            captured["deps"] = deps
            return SimpleNamespace(
                output=valid_update(),
                usage=lambda: SimpleNamespace(model_dump=dict),
            )

    monkeypatch.setattr(release_notes, "Agent", FakeAgent)
    monkeypatch.setattr(release_notes, "build_pydantic_ai_model", lambda config: "fake-model")

    update, usage = asyncio.run(
        release_notes.run_release_notes_agent(
            goal="Draft release notes.",
            audience="end_users",
            evidence=EvidenceBundle(),
            config=ProviderConfig(),
        )
    )

    assert captured["retries"] == release_notes.RELEASE_NOTES_AGENT_RETRIES
    assert "title, summary" in captured["instructions"]
    assert update.title == "Release title"
    assert usage["prompt_strategy"] == "release_notes_agent_tools"


def test_close_model_client_closes_async_openai_client() -> None:
    closed = False

    class FakeClient:
        async def close(self) -> None:
            nonlocal closed
            closed = True

    asyncio.run(release_notes.close_model_client(SimpleNamespace(client=FakeClient())))

    assert closed


def test_agent_usage_prefers_model_dump_without_calling_usage() -> None:
    class CallableUsage:
        def __call__(self) -> None:
            raise AssertionError("deprecated usage() should not be called")

        def model_dump(self) -> dict[str, int]:
            return {"total_tokens": 42}

    result = SimpleNamespace(usage=CallableUsage())

    assert release_notes.agent_usage(result) == {"total_tokens": 42}


def test_agent_usage_serializes_callable_dataclass_without_calling_usage() -> None:
    @dataclass
    class CallableUsage:
        total_tokens: int

        def __call__(self) -> None:
            raise AssertionError("deprecated usage() should not be called")

    result = SimpleNamespace(usage=CallableUsage(total_tokens=42))

    assert release_notes.agent_usage(result) == {"total_tokens": 42}
