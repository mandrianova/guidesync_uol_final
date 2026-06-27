from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from guidesync_agent.schemas import (
    LLMConversationStatus,
    LLMConversationTranscript,
    LLMRedactionStatus,
    ModelRole,
    ProviderKind,
)
from guidesync_agent.services.llm_transcript_payloads import (
    conversation_id_for,
    endpoint_metadata,
    local_http_transcript_payload,
    mapping_payload,
    message_stats,
    model_settings,
    pydantic_ai_transcript_payload,
    sanitize_secret_value,
    tool_call_count,
    transcript_messages,
    transcript_tool_calls,
)
from guidesync_agent.storage import create_llm_transcript_store

__all__ = [
    "local_http_transcript_payload",
    "pydantic_ai_transcript_payload",
    "read_transcript_artifact",
    "record_llm_transcript_from_metadata",
]


def record_llm_transcript_from_metadata(
    *,
    project_id: str | None,
    run_id: str | None,
    workflow_task_id: str | None,
    model_role: ModelRole,
    provider: ProviderKind,
    model: str,
    metadata: Mapping[str, Any],
    started_at: datetime,
    completed_at: datetime | None,
    model_call_id: str | None = None,
    token_ledger_entry_id: str | None = None,
    endpoint_type: str | None = None,
    status: LLMConversationStatus = LLMConversationStatus.COMPLETED,
    error: str | None = None,
) -> LLMConversationTranscript | None:
    raw_payload = metadata.get("llm_transcript_payload")
    if not isinstance(raw_payload, Mapping):
        return None
    payload = sanitize_secret_value(raw_payload)
    transcript = build_transcript(
        payload=payload,
        project_id=project_id,
        run_id=run_id,
        workflow_task_id=workflow_task_id,
        model_role=model_role,
        provider=provider,
        model=model,
        metadata=metadata,
        started_at=started_at,
        completed_at=completed_at,
        model_call_id=model_call_id,
        token_ledger_entry_id=token_ledger_entry_id,
        endpoint_type=endpoint_type,
        status=status,
        error=error,
    )
    artifact_ref = write_transcript_artifact(transcript, payload)
    transcript = transcript.model_copy(update={"transcript_artifact_ref": artifact_ref})
    return create_llm_transcript_store().save(transcript)


def build_transcript(
    *,
    payload: Mapping[str, Any],
    project_id: str | None,
    run_id: str | None,
    workflow_task_id: str | None,
    model_role: ModelRole,
    provider: ProviderKind,
    model: str,
    metadata: Mapping[str, Any],
    started_at: datetime,
    completed_at: datetime | None,
    model_call_id: str | None,
    token_ledger_entry_id: str | None,
    endpoint_type: str | None,
    status: LLMConversationStatus,
    error: str | None,
) -> LLMConversationTranscript:
    now = datetime.now(UTC)
    messages = transcript_messages(payload)
    tool_calls = transcript_tool_calls(payload)
    prompt_metadata = mapping_payload(payload, "prompt_metadata")
    provider_metadata = mapping_payload(payload, "provider_metadata")
    tool_summary = transcript_tool_summary(payload, tool_calls)
    diagnostics = mapping_payload(payload, "diagnostics")
    if error:
        diagnostics = {**diagnostics, "error": error}
    return LLMConversationTranscript(
        id=f"llm-conv-{uuid4().hex[:12]}",
        project_id=project_id,
        run_id=run_id,
        workflow_task_id=workflow_task_id,
        model_call_id=model_call_id,
        model_role=model_role,
        provider=provider,
        model=model,
        endpoint_type=endpoint_type,
        conversation_id=conversation_id_for(run_id, workflow_task_id, model_role),
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        created_at=now,
        updated_at=now,
        message_count=len(messages),
        tool_call_count=tool_call_count(payload, tool_calls),
        token_ledger_entry_id=token_ledger_entry_id,
        redaction_status=LLMRedactionStatus.REDACTED,
        prompt_metadata=prompt_metadata,
        provider_metadata=provider_metadata,
        endpoint_metadata=endpoint_metadata(metadata),
        model_settings=model_settings(metadata),
        message_stats=message_stats(messages),
        tool_summary=tool_summary,
        redaction_metadata={"policy_version": "llm-transcript-redaction-v1"},
        diagnostics=diagnostics,
        messages=messages,
        tool_calls=tool_calls,
    )


def transcript_tool_summary(
    payload: Mapping[str, Any],
    tool_calls: list[Any],
) -> dict[str, Any]:
    summary = mapping_payload(payload, "tool_summary")
    if tool_calls and "tool_calls" not in summary:
        return {
            **summary,
            "tool_calls": [
                item.model_dump(mode="json")
                for item in tool_calls
                if hasattr(item, "model_dump")
            ],
        }
    return summary


def read_transcript_artifact(transcript_id: str) -> LLMConversationTranscript | None:
    transcript = create_llm_transcript_store().get(transcript_id)
    if transcript is None or not transcript.transcript_artifact_ref:
        return transcript
    path = Path(transcript.transcript_artifact_ref)
    if not path.exists():
        return transcript.model_copy(
            update={
                "diagnostics": {
                    **transcript.diagnostics,
                    "artifact_missing": transcript.transcript_artifact_ref,
                }
            }
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return transcript.model_copy(
        update={
            "messages": transcript_messages(payload),
            "tool_calls": transcript_tool_calls(payload),
        }
    )


def write_transcript_artifact(
    transcript: LLMConversationTranscript,
    payload: Mapping[str, Any],
) -> str:
    root = transcript_output_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{transcript.id}.json"
    artifact_payload = {
        "transcript": transcript.model_dump(
            mode="json",
            exclude={"messages", "tool_calls"},
        ),
        "messages": [message.model_dump(mode="json") for message in transcript.messages],
        "tool_calls": [tool.model_dump(mode="json") for tool in transcript.tool_calls],
        "payload": payload,
    }
    path.write_text(json.dumps(artifact_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def transcript_output_dir() -> Path:
    return Path(os.environ.get("GUIDESYNC_LLM_TRANSCRIPT_OUTPUT_DIR", "logs/llm-transcripts"))
