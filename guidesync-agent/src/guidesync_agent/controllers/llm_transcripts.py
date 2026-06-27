from __future__ import annotations

from guidesync_agent.schemas import LLMConversationTranscript, LLMTranscriptSummary
from guidesync_agent.services.llm_transcripts import read_transcript_artifact
from guidesync_agent.storage import create_llm_transcript_store


def list_run_transcripts(run_id: str) -> list[LLMTranscriptSummary]:
    return create_llm_transcript_store().list_for_run(run_id)


def list_workflow_task_transcripts(workflow_task_id: str) -> list[LLMTranscriptSummary]:
    return create_llm_transcript_store().list_for_workflow_task(workflow_task_id)


def get_transcript(transcript_id: str) -> LLMConversationTranscript | None:
    return create_llm_transcript_store().get(transcript_id)


def get_transcript_artifact(transcript_id: str) -> LLMConversationTranscript | None:
    return read_transcript_artifact(transcript_id)
