from __future__ import annotations

from fastapi import APIRouter, HTTPException

from guidesync_agent.controllers import llm_transcripts as controller
from guidesync_agent.schemas import LLMConversationTranscript, LLMTranscriptSummary

router = APIRouter(prefix="/llm-transcripts", tags=["LLM transcripts"])
run_router = APIRouter(prefix="/runs/{run_id}/llm-transcripts", tags=["LLM transcripts"])
workflow_task_router = APIRouter(
    prefix="/workflow-tasks/{workflow_task_id}/llm-transcripts",
    tags=["LLM transcripts"],
)


@run_router.get("")
async def list_run_transcripts(run_id: str) -> list[LLMTranscriptSummary]:
    return controller.list_run_transcripts(run_id)


@workflow_task_router.get("")
async def list_workflow_task_transcripts(
    workflow_task_id: str,
) -> list[LLMTranscriptSummary]:
    return controller.list_workflow_task_transcripts(workflow_task_id)


@router.get("/{transcript_id}")
async def get_transcript(transcript_id: str) -> LLMConversationTranscript:
    transcript = controller.get_transcript(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found.")
    return transcript


@router.get("/{transcript_id}/artifact")
async def get_transcript_artifact(transcript_id: str) -> LLMConversationTranscript:
    transcript = controller.get_transcript_artifact(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found.")
    return transcript
