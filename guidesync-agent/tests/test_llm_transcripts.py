from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from guidesync_agent.api import app
from guidesync_agent.schemas import ModelRole, ProviderKind
from guidesync_agent.services.llm_transcripts import (
    local_http_transcript_payload,
    read_transcript_artifact,
    record_llm_transcript_from_metadata,
)


def test_llm_transcript_persists_metadata_artifact_and_redacts_secrets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'transcripts.db'}"
    transcript_dir = tmp_path / "transcripts"
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setenv("GUIDESYNC_STORAGE_AUTO_CREATE_SCHEMA", "1")
    monkeypatch.setenv("GUIDESYNC_LLM_TRANSCRIPT_OUTPUT_DIR", str(transcript_dir))

    payload = local_http_transcript_payload(
        system_prompt="system",
        user_prompt="user",
        request_payload={
            "model": "openai:test-model",
            "api_key": "secret-key",
            "messages": [{"role": "user", "content": "hello"}],
        },
        response_payload={
            "id": "response-1",
            "model": "openai:test-model",
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            "choices": [{"finish_reason": "stop"}],
        },
        output_text='{"summary":"ok"}',
        prompt_metadata={"prompt_version": "test-v1"},
    )

    transcript = record_llm_transcript_from_metadata(
        project_id="project-1",
        run_id="run-1",
        workflow_task_id="task-1",
        model_role=ModelRole.ORCHESTRATOR,
        provider=ProviderKind.LOCAL_HTTP,
        model="openai:test-model",
        metadata={"llm_transcript_payload": payload, "base_url": "https://secret@example.test/v1"},
        started_at=datetime(2026, 6, 27, tzinfo=UTC),
        completed_at=datetime(2026, 6, 27, tzinfo=UTC),
        model_call_id="call-1",
        token_ledger_entry_id="call-1",
        endpoint_type="openai_compatible",
    )

    assert transcript is not None
    assert transcript.message_count == 3
    assert transcript.transcript_artifact_ref is not None
    artifact = Path(transcript.transcript_artifact_ref).read_text(encoding="utf-8")
    assert "secret-key" not in artifact
    assert "[REDACTED]" in artifact
    loaded = read_transcript_artifact(transcript.id)
    assert loaded is not None
    assert loaded.messages[0].content == "system"


def test_llm_transcript_api_lists_and_reads_artifact(monkeypatch, tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'transcripts-api.db'}"
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setenv("GUIDESYNC_STORAGE_AUTO_CREATE_SCHEMA", "1")
    monkeypatch.setenv("GUIDESYNC_LLM_TRANSCRIPT_OUTPUT_DIR", str(tmp_path / "api-transcripts"))
    transcript = record_llm_transcript_from_metadata(
        project_id="project-1",
        run_id="run-api",
        workflow_task_id="task-api",
        model_role=ModelRole.CODE_CHANGE_ANALYSIS,
        provider=ProviderKind.LOCAL_HTTP,
        model="openai:test-model",
        metadata={
            "llm_transcript_payload": local_http_transcript_payload(
                system_prompt="system",
                user_prompt="user",
                request_payload={"model": "openai:test-model"},
                response_payload={"model": "openai:test-model"},
                output_text="{}",
            )
        },
        started_at=datetime(2026, 6, 27, tzinfo=UTC),
        completed_at=datetime(2026, 6, 27, tzinfo=UTC),
    )
    assert transcript is not None
    client = TestClient(app)

    run_response = client.get("/runs/run-api/llm-transcripts")
    task_response = client.get("/workflow-tasks/task-api/llm-transcripts")
    artifact_response = client.get(f"/llm-transcripts/{transcript.id}/artifact")

    assert run_response.status_code == 200
    assert run_response.json()[0]["id"] == transcript.id
    assert task_response.status_code == 200
    assert task_response.json()[0]["workflow_task_id"] == "task-api"
    assert artifact_response.status_code == 200
    assert artifact_response.json()["messages"][0]["content"] == "system"
