from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from guidesync_agent.agent_runtime import release_notes
from guidesync_agent.agent_runtime.pydantic_ai import agent_usage, close_model_client
from guidesync_agent.prompts.release_notes import (
    ReleaseNotesPromptInput,
    build_release_notes_task_prompt,
)
from guidesync_agent.schemas import (
    AnalysisArtifactDigest,
    AnalysisArtifactManifest,
    AnalysisArtifactRef,
    DocumentationUpdateModelOutput,
    EvidenceBundle,
    ProviderConfig,
)


def valid_update() -> DocumentationUpdateModelOutput:
    return DocumentationUpdateModelOutput(
        title="Release title",
        summary="Release summary",
        user_facing_change="Users can review the release.",
        proposed_update_markdown="## Release title\n\nUsers can review the release.",
        evidence_refs=[],
        reviewer_notes="Ready for human review.",
        change_ids=["file-summary-1"],
        change_titles=["Navigation update"],
        change_summaries=["Navigation is easier to use."],
        change_user_facing_details=["The current state is visible."],
        change_how_to_markdown=["Open the navigation from the header."],
        change_evidence_refs=["diff:repo:navigation\nfile:repo:navigation"],
    )


def test_release_notes_agent_uses_native_output_with_optional_tools(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_pydantic_agent(request):
        captured.update(vars(request))
        return SimpleNamespace(
            output=valid_update(),
            usage={"orchestrator_structured_output_mode": "native"},
        )

    monkeypatch.setattr(release_notes, "run_pydantic_agent", fake_run_pydantic_agent)

    update, usage = asyncio.run(
        release_notes.run_release_notes_agent(
            release_notes.ReleaseNotesGenerationInput(
                goal="Draft release notes.",
                audience="end_users",
                evidence=EvidenceBundle(),
            ),
            config=ProviderConfig(),
        )
    )

    assert captured["retries"] == release_notes.RELEASE_NOTES_AGENT_RETRIES
    assert captured["requires_tools"] is False
    assert "DocumentationUpdateModelOutput" in captured["instructions"]
    assert captured["output_model"] is DocumentationUpdateModelOutput
    assert update.title == "Release title"
    assert len(update.changes) == 1
    assert update.changes[0].id == "file-summary-1"
    assert update.changes[0].evidence_refs == [
        "diff:repo:navigation",
        "file:repo:navigation",
    ]
    assert usage["prompt_strategy"] == "release_notes_agent_tools"
    assert usage["release_notes_agent_prompt_id"] == "release_notes.agent_instructions"
    assert usage["release_notes_agent_prompt_version"] == "release-notes-agent-v5"
    assert len(usage["release_notes_agent_prompt_sha256"]) == 64
    assert usage["release_notes_agent_structured_output_mode"] == "native"


def test_release_notes_prompt_contains_compact_work_plan_checkpoint() -> None:
    prompt = build_release_notes_task_prompt(
        ReleaseNotesPromptInput(
            goal="Draft release notes.",
            audience="end_users",
            evidence=EvidenceBundle(),
            analysis_manifest=AnalysisArtifactManifest(
                run_id="run-1",
                plan_task_id="plan-1",
                planned_paths=["repo:src/app.py", "repo:tests/test_app.py"],
                completed_unit_ids=["unit-1"],
                artifacts=[
                    AnalysisArtifactRef(
                        id="artifact-1",
                        work_unit_id="unit-1",
                        repository_id="repo",
                        path="src/app.py",
                        artifact_ref="/tmp/artifact-1.json",
                        digest=AnalysisArtifactDigest(
                            technical_summary="Streams rows incrementally.",
                            product_impact="Developers can return a streamed response.",
                            documentation_search_intents=["streaming response"],
                            evidence_refs=["diff:repo:src/app.py"],
                        ),
                    ),
                ],
            ),
        ),
    )

    assert "plan task plan-1" in prompt
    assert "2 planned file(s)" in prompt
    assert "1 completed unit(s)" in prompt
    assert "Compact analysis manifest" in prompt
    assert "path=src/app.py" in prompt
    assert "Streams rows incrementally" in prompt
    assert "diff:repo:src/app.py" in prompt
    assert "do not reopen every artifact" in prompt
    assert "one change row per distinct user-facing change" in prompt
    assert "Write every user-facing field in English" in prompt


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
