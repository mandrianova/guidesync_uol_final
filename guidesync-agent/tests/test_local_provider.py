from __future__ import annotations

from pydantic_ai import NativeOutput, PromptedOutput, ToolOutput

from guidesync_agent.llm.local_http import (
    extract_json_object,
    local_chat_payload,
    local_chat_url,
    local_message_content,
)
from guidesync_agent.llm.structured_output import (
    pydantic_ai_output_type,
    select_structured_output,
)
from guidesync_agent.schemas import (
    CommitEvidence,
    DiffHint,
    DocumentationEvidence,
    DocumentationUpdate,
    EvidenceBundle,
    FileChange,
    LocalHTTPChatEndpoint,
    ProviderConfig,
    ProviderKind,
    StructuredOutputMode,
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


def test_openai_compatible_local_payload_uses_native_json_schema() -> None:
    config = ProviderConfig(
        provider=ProviderKind.LOCAL_HTTP,
        model="openai:google/gemma-4-31b-qat",
        base_url="http://localhost:1234/v1",
    )
    selection = select_structured_output(config, DocumentationUpdate, requires_tools=False)

    payload = local_chat_payload(
        config,
        "system",
        "input",
        output_model=DocumentationUpdate,
        selection=selection,
        endpoint=LocalHTTPChatEndpoint.OPENAI_CHAT_COMPLETIONS,
    )

    assert selection.mode == StructuredOutputMode.NATIVE
    assert payload["model"] == "google/gemma-4-31b-qat"
    assert payload["messages"][0] == {"role": "system", "content": "system"}
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["name"] == "documentationupdate"
    assert payload["response_format"]["json_schema"]["schema"]["title"] == "DocumentationUpdate"
    assert payload["response_format"]["json_schema"]["strict"] is True


def test_custom_local_payload_uses_prompted_schema_fallback() -> None:
    config = ProviderConfig(
        provider=ProviderKind.LOCAL_HTTP,
        model="google/gemma-4-31b-qat",
        base_url="http://localhost:1234/api/v1/chat",
    )
    selection = select_structured_output(config, DocumentationUpdate, requires_tools=False)

    payload = local_chat_payload(
        config,
        "system",
        "input",
        output_model=DocumentationUpdate,
        selection=selection,
        endpoint=LocalHTTPChatEndpoint.CUSTOM_CHAT,
    )

    assert selection.mode == StructuredOutputMode.PROMPTED
    assert "response_format" not in payload
    assert payload["structured_output_mode"] == "prompted"
    assert payload["output_schema"]["title"] == "DocumentationUpdate"
    assert "Structured output JSON schema generated from Pydantic" in payload["input"]


def test_local_chat_url_appends_openai_chat_completions_path() -> None:
    assert (
        local_chat_url(
            "http://localhost:1234/v1",
            LocalHTTPChatEndpoint.OPENAI_CHAT_COMPLETIONS,
        )
        == "http://localhost:1234/v1/chat/completions"
    )
    assert (
        local_chat_url(
            "http://localhost:1234/v1/chat/completions",
            LocalHTTPChatEndpoint.OPENAI_CHAT_COMPLETIONS,
        )
        == "http://localhost:1234/v1/chat/completions"
    )


def test_structured_output_selection_uses_tool_for_tool_agents() -> None:
    selection = select_structured_output(
        ProviderConfig(),
        DocumentationUpdate,
        requires_tools=True,
    )

    assert selection.mode == StructuredOutputMode.TOOL
    assert isinstance(pydantic_ai_output_type(DocumentationUpdate, selection), ToolOutput)


def test_structured_output_selection_can_force_native_or_prompted() -> None:
    native_selection = select_structured_output(
        ProviderConfig(metadata={"structured_output_mode": "native"}),
        DocumentationUpdate,
        requires_tools=False,
    )
    prompted_selection = select_structured_output(
        ProviderConfig(metadata={"structured_output_mode": "prompted"}),
        DocumentationUpdate,
        requires_tools=False,
    )

    assert isinstance(pydantic_ai_output_type(DocumentationUpdate, native_selection), NativeOutput)
    assert isinstance(
        pydantic_ai_output_type(DocumentationUpdate, prompted_selection),
        PromptedOutput,
    )


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
                    DiffHint(file=f"src/file-{item}.ts", hint="hint " * 200) for item in range(20)
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
