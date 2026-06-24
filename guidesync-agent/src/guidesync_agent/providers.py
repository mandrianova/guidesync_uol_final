from __future__ import annotations

from guidesync_agent.llm.providers import (
    LocalHTTPProvider,
    MockProvider,
    ModelProvider,
    PydanticAIProvider,
    extract_json_object,
    local_chat_payload,
    local_message_content,
    post_local_chat,
    provider_for,
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

__all__ = [
    "LocalHTTPProvider",
    "MODEL_EVIDENCE_MAX_COMMITS",
    "MODEL_EVIDENCE_MAX_DIFF_HINTS",
    "MockProvider",
    "ModelProvider",
    "PydanticAIProvider",
    "chunk_evidence_for_model",
    "compact_evidence_for_model",
    "extract_json_object",
    "find_commit",
    "find_documentation",
    "local_chat_payload",
    "local_message_content",
    "post_local_chat",
    "provider_for",
    "register_evidence_agent_tools",
]
