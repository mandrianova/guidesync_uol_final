from __future__ import annotations

from guidesync_agent.llm.providers import (
    extract_json_object,
    local_chat_payload,
    local_message_content,
)
from guidesync_agent.schemas import (
    CommitEvidence,
    DiffHint,
    DocumentationEvidence,
    EvidenceBundle,
    FileChange,
    ProviderConfig,
)
from guidesync_agent.tools.evidence import (
    MODEL_EVIDENCE_MAX_COMMITS,
    MODEL_EVIDENCE_MAX_DIFF_HINTS,
    chunk_evidence_for_model,
    compact_evidence_for_model,
    find_commit,
    find_documentation,
    register_evidence_agent_tools,
)


def test_local_message_content_uses_last_message_output() -> None:
    response = {
        "output": [
            {"type": "reasoning", "content": "hidden reasoning"},
            {"type": "message", "content": '{"title": "Update"}'},
        ]
    }

    assert local_message_content(response) == '{"title": "Update"}'


def test_local_chat_payload_includes_thinking_only_when_configured() -> None:
    default_payload = local_chat_payload(
        ProviderConfig(model="google/gemma-4-31b-qat"),
        "system",
        "input",
    )
    thinking_payload = local_chat_payload(
        ProviderConfig(model="google/gemma-4-31b-qat", thinking="high"),
        "system",
        "input",
    )

    assert "thinking" not in default_payload
    assert thinking_payload["thinking"] == "high"


def test_extract_json_object_accepts_fenced_json() -> None:
    payload = extract_json_object('```json\n{"title": "Update"}\n```')

    assert payload == {"title": "Update"}


def test_compact_evidence_for_model_limits_prompt_payload() -> None:
    evidence = EvidenceBundle(
        repositories=["https://github.com/example/project"],
        commits=[
            CommitEvidence(
                repo="example/project",
                sha=f"{index:040x}",
                short_sha=f"{index:08x}",
                date="2026-06-14T00:00:00Z",
                subject=f"Visible workflow change {index}",
                body="body " * 500,
                files=[f"src/file-{item}.ts" for item in range(40)],
                file_stats=[FileChange(file=f"src/file-{item}.ts") for item in range(30)],
                diff_hints=[
                    DiffHint(file=f"src/file-{item}.ts", hint="hint " * 200)
                    for item in range(20)
                ],
                user_facing_score=index % 5,
            )
            for index in range(MODEL_EVIDENCE_MAX_COMMITS + 10)
        ],
        documentation=[
            DocumentationEvidence(
                name="docs",
                path="docs/guide.md",
                excerpt="documentation " * 1000,
            )
        ],
        warnings=[f"warning {index}" for index in range(40)],
    )

    compacted, stats = compact_evidence_for_model(evidence)

    assert len(compacted.commits) == MODEL_EVIDENCE_MAX_COMMITS
    assert len(compacted.commits[0].diff_hints) == MODEL_EVIDENCE_MAX_DIFF_HINTS
    assert len(compacted.commits[0].files) < len(evidence.commits[0].files)
    assert compacted.commits[0].body.endswith("...[truncated]")
    assert stats["prompt_evidence_commits_omitted"] == 10
    assert stats["prompt_evidence_compacted"] is True


def test_chunk_evidence_for_model_preserves_all_commits_across_chunks() -> None:
    evidence = EvidenceBundle(
        commits=[
            CommitEvidence(
                repo="example/project",
                sha=f"{index:040x}",
                short_sha=f"{index:08x}",
                date="2026-06-14T00:00:00Z",
                subject=f"Change {index}",
            )
            for index in range(MODEL_EVIDENCE_MAX_COMMITS + 1)
        ]
    )

    chunks = chunk_evidence_for_model(evidence)

    assert len(chunks) == 2
    assert sum(len(chunk.commits) for chunk in chunks) == MODEL_EVIDENCE_MAX_COMMITS + 1


def test_evidence_lookup_helpers_match_prefix_and_doc_path() -> None:
    evidence = EvidenceBundle(
        commits=[
            CommitEvidence(
                repo="example/project",
                sha="abcdef1234567890",
                short_sha="abcdef12",
                date="2026-06-14T00:00:00Z",
                subject="Change",
            )
        ],
        documentation=[
            DocumentationEvidence(name="Guide", path="docs/guide.md", excerpt="Content")
        ],
    )

    assert find_commit(evidence, "abcdef") is evidence.commits[0]
    assert find_documentation(evidence, "docs/guide.md") is evidence.documentation[0]


def test_evidence_agent_tools_register_with_pydantic_ai() -> None:
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    agent = Agent(TestModel(), output_type=str)

    register_evidence_agent_tools(agent)
