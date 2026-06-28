from __future__ import annotations

from sqlalchemy.engine import Row

from guidesync_agent.schemas import (
    LLMConversationStatus,
    LLMConversationTranscript,
    LLMMessageRole,
    LLMMessageSource,
    LLMRedactionStatus,
    LLMTranscriptEvent,
    LLMTranscriptEventKind,
    LLMTranscriptSummary,
    ModelRole,
    ProviderKind,
)


def llm_conversation_values(transcript: LLMConversationTranscript) -> dict[str, object]:
    return {
        "id": transcript.id,
        "project_id": transcript.project_id,
        "run_id": transcript.run_id,
        "workflow_task_id": transcript.workflow_task_id,
        "parent_conversation_id": transcript.parent_conversation_id,
        "model_call_id": transcript.model_call_id,
        "model_role": transcript.model_role.value,
        "provider": transcript.provider.value,
        "model": transcript.model,
        "endpoint_type": transcript.endpoint_type,
        "conversation_id": transcript.conversation_id,
        "turn_index": transcript.turn_index,
        "status": transcript.status.value,
        "started_at": transcript.started_at,
        "completed_at": transcript.completed_at,
        "created_at": transcript.created_at,
        "updated_at": transcript.updated_at,
        "message_count": transcript.message_count,
        "tool_call_count": transcript.tool_call_count,
        "token_ledger_entry_id": transcript.token_ledger_entry_id,
        "transcript_artifact_ref": transcript.transcript_artifact_ref,
        "full_history_artifact_ref": transcript.full_history_artifact_ref,
        "redaction_status": transcript.redaction_status.value,
        "prompt_metadata": transcript.prompt_metadata,
        "provider_metadata": transcript.provider_metadata,
        "endpoint_metadata": transcript.endpoint_metadata,
        "model_settings": transcript.model_settings,
        "message_stats": transcript.message_stats,
        "tool_summary": transcript.tool_summary,
        "redaction_metadata": transcript.redaction_metadata,
        "diagnostics": transcript.diagnostics,
    }

def llm_conversation_event_values(event: LLMTranscriptEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "conversation_id": event.conversation_id,
        "sequence": event.sequence,
        "event_kind": event.event_kind.value,
        "role": event.role.value if event.role else None,
        "source": event.source.value,
        "name": event.name,
        "content": event.content,
        "tool_call_id": event.tool_call_id,
        "tool_name": event.tool_name,
        "arguments": event.arguments,
        "result_payload": event.result_payload,
        "result_status": event.result_status,
        "evidence_refs": event.evidence_refs,
        "artifact_refs": event.artifact_refs,
        "usage": event.usage,
        "metadata": event.metadata,
        "error_message": event.error_message,
        "created_at": event.created_at,
    }

def llm_conversation_from_row(row: Row) -> LLMConversationTranscript:
    return LLMConversationTranscript(
        id=row.id,
        project_id=row.project_id,
        run_id=row.run_id,
        workflow_task_id=row.workflow_task_id,
        parent_conversation_id=row.parent_conversation_id,
        model_call_id=row.model_call_id,
        model_role=ModelRole(row.model_role),
        provider=ProviderKind(row.provider),
        model=row.model,
        endpoint_type=row.endpoint_type,
        conversation_id=row.conversation_id,
        turn_index=row.turn_index,
        status=LLMConversationStatus(row.status),
        started_at=row.started_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        message_count=row.message_count,
        tool_call_count=row.tool_call_count,
        token_ledger_entry_id=row.token_ledger_entry_id,
        transcript_artifact_ref=row.transcript_artifact_ref,
        full_history_artifact_ref=row.full_history_artifact_ref,
        redaction_status=LLMRedactionStatus(row.redaction_status),
        prompt_metadata=dict(row.prompt_metadata or {}),
        provider_metadata=dict(row.provider_metadata or {}),
        endpoint_metadata=dict(row.endpoint_metadata or {}),
        model_settings=dict(row.model_settings or {}),
        message_stats=dict(row.message_stats or {}),
        tool_summary=dict(row.tool_summary or {}),
        redaction_metadata=dict(row.redaction_metadata or {}),
        diagnostics=dict(row.diagnostics or {}),
    )

def llm_conversation_event_from_row(row: Row) -> LLMTranscriptEvent:
    role = None
    if row.role:
        try:
            role = LLMMessageRole(row.role)
        except ValueError:
            role = LLMMessageRole.PROVIDER
    try:
        source = LLMMessageSource(row.source)
    except ValueError:
        source = LLMMessageSource.NORMALIZED
    return LLMTranscriptEvent(
        id=row.id,
        conversation_id=row.conversation_id,
        sequence=row.sequence,
        event_kind=LLMTranscriptEventKind(row.event_kind),
        role=role,
        source=source,
        name=row.name,
        content=row.content or "",
        tool_call_id=row.tool_call_id,
        tool_name=row.tool_name,
        arguments=dict(row.arguments or {}),
        result_payload=dict(row.result_payload or {}),
        result_status=row.result_status,
        evidence_refs=list(row.evidence_refs or []),
        artifact_refs=list(row.artifact_refs or []),
        usage=dict(row.usage or {}),
        metadata=dict(row.metadata or {}),
        error_message=row.error_message,
        created_at=row.created_at,
    )

def llm_transcript_summary_from_row(row: Row) -> LLMTranscriptSummary:
    return LLMTranscriptSummary(
        id=row.id,
        project_id=row.project_id,
        run_id=row.run_id,
        workflow_task_id=row.workflow_task_id,
        model_call_id=row.model_call_id,
        model_role=ModelRole(row.model_role),
        provider=ProviderKind(row.provider),
        model=row.model,
        status=LLMConversationStatus(row.status),
        started_at=row.started_at,
        completed_at=row.completed_at,
        message_count=row.message_count,
        tool_call_count=row.tool_call_count,
        transcript_artifact_ref=row.transcript_artifact_ref,
    )
