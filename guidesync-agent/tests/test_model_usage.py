from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from guidesync_agent.api import app
from guidesync_agent.models import model_call_ledger_table
from guidesync_agent.schemas import (
    ModelCallLedgerEntry,
    ModelCallStatus,
    ModelRole,
    ProjectProfileSnapshot,
    ProjectProfileStatus,
    ProviderConfig,
    ProviderKind,
    ProviderRunMetadata,
    TokenUsageBreakdown,
    TokenUsageSource,
)
from guidesync_agent.services.model_usage import (
    build_model_call_ledger_entry,
    endpoint_host_hash,
    normalize_token_usage,
    record_model_call_ledger_entry,
)
from guidesync_agent.services.project_profile import record_project_profile_model_usage
from guidesync_agent.storage import DatabaseModelUsageStore


def test_openai_compatible_usage_normalization() -> None:
    breakdown, source = normalize_token_usage(
        {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 7,
                "total_tokens": 21,
                "prompt_tokens_details": {"cached_tokens": 3},
                "completion_tokens_details": {"reasoning_tokens": 4},
            }
        },
        tool_call_count=2,
    )

    assert source == TokenUsageSource.PROVIDER_REPORTED
    assert breakdown.input_tokens == 10
    assert breakdown.output_tokens == 7
    assert breakdown.reasoning_tokens == 4
    assert breakdown.cached_input_tokens == 3
    assert breakdown.provider_reported_total_tokens == 21
    assert breakdown.tool_call_count == 2


def test_anthropic_and_gemini_usage_normalization() -> None:
    anthropic, anthropic_source = normalize_token_usage(
        {
            "input_tokens": 100,
            "output_tokens": 30,
            "cache_creation_input_tokens": 12,
            "cache_read_input_tokens": 40,
        }
    )
    gemini, gemini_source = normalize_token_usage(
        {
            "promptTokenCount": 55,
            "candidatesTokenCount": 20,
            "totalTokenCount": 75,
            "thoughtsTokenCount": 5,
        }
    )

    assert anthropic_source == TokenUsageSource.PROVIDER_REPORTED
    assert anthropic.input_tokens == 100
    assert anthropic.output_tokens == 30
    assert anthropic.cache_write_tokens == 12
    assert anthropic.cached_input_tokens == 40
    assert gemini_source == TokenUsageSource.PROVIDER_REPORTED
    assert gemini.provider_reported_total_tokens == 75
    assert gemini.reasoning_tokens == 5


def test_missing_usage_falls_back_to_local_estimate_and_hashes_endpoint() -> None:
    breakdown, source = normalize_token_usage(
        {},
        fallback_input_text="12345678",
        fallback_output_text="1234",
    )

    assert source == TokenUsageSource.LOCAL_ESTIMATE
    assert breakdown.input_tokens == 2
    assert breakdown.output_tokens == 1
    assert breakdown.locally_estimated_total_tokens == 3
    assert endpoint_host_hash("https://token:secret@example.test/v1") == endpoint_host_hash(
        "https://example.test/v1"
    )


def test_prompt_metadata_falls_back_to_local_estimate() -> None:
    breakdown, source = normalize_token_usage({"prompt_input_chars": 12})

    assert source == TokenUsageSource.LOCAL_ESTIMATE
    assert breakdown.input_tokens == 3
    assert breakdown.locally_estimated_total_tokens == 3


def test_database_model_usage_store_records_and_summarizes(tmp_path: Path) -> None:
    store = DatabaseModelUsageStore(f"sqlite+pysqlite:///{tmp_path / 'usage.db'}")
    store.record(sample_entry())

    entries = store.list_for_run("run-1")
    summary = store.summarize_run("run-1")

    assert entries[0].id == "call-1"
    assert entries[0].base_url_host_hash == "hash-only"
    assert summary.total_tokens == 12
    assert summary.calls == 1
    assert summary.by_role[0].key == ModelRole.CODE_CHANGE_ANALYSIS.value
    assert summary.by_provider[0].key == ProviderKind.LOCAL_HTTP.value
    assert summary.by_model[0].key == "openai:test-model"


def test_provider_metadata_records_model_usage(monkeypatch, tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'metadata-usage.db'}"
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    config = ProviderConfig(
        provider=ProviderKind.LOCAL_HTTP,
        model="openai:test-model",
        base_url="https://token:secret@example.test/v1",
        metadata={"endpoint_type": "openai_compatible", "model_profile_id": "profile-1"},
    )
    metadata = ProviderRunMetadata(
        provider=ProviderKind.LOCAL_HTTP.value,
        model="openai:test-model",
        started_at=datetime(2026, 6, 27, tzinfo=UTC),
        completed_at=datetime(2026, 6, 27, tzinfo=UTC),
        latency_ms=25,
        token_usage={"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12},
    )

    entry = record_model_call_ledger_entry(
        build_model_call_ledger_entry(
            run_id="run-1",
            project_id="project-1",
            role=ModelRole.ORCHESTRATOR,
            config=config,
            metadata=metadata,
            workflow_task_id="workflow-task-1",
        )
    )

    stored = DatabaseModelUsageStore(database_url).list_for_run("run-1")[0]
    assert entry.id == "run-1-orchestrator"
    assert stored.usage_source == TokenUsageSource.PROVIDER_REPORTED
    assert stored.usage.provider_reported_total_tokens == 12
    assert stored.endpoint_type == "openai_compatible"
    assert stored.model_profile_id == "profile-1"
    assert stored.workflow_task_id == "workflow-task-1"
    assert stored.base_url_host_hash == endpoint_host_hash("https://example.test/v1")


def test_project_profile_metadata_records_model_usage(monkeypatch, tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'profile-usage.db'}"
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    profile = ProjectProfileSnapshot(
        id="profile-1",
        project_id="project-1",
        status=ProjectProfileStatus.COMPLETED,
        prompt_version="project-profile-test",
        model_metadata={
            "provider": ProviderKind.LOCAL_HTTP.value,
            "model": "openai:test-model",
            "base_url": "https://secret@example.test/v1",
            "endpoint_type": "openai_compatible",
            "latency_ms": 50,
            "prompt_input_chars": 20,
        },
        completed_at=datetime(2026, 6, 27, tzinfo=UTC),
    )

    updated = record_project_profile_model_usage(
        profile,
        workflow_task_id="workflow-task-profile",
    )

    engine = create_engine(database_url)
    with engine.begin() as connection:
        row = connection.execute(select(model_call_ledger_table)).one()
    assert not updated.warnings
    assert row.id == "profile-1-project_profile_file_reader"
    assert row.project_id == "project-1"
    assert row.workflow_task_id == "workflow-task-profile"
    assert row.run_id is None
    assert row.usage_source == TokenUsageSource.LOCAL_ESTIMATE.value
    assert row.locally_estimated_total_tokens == 5


def test_model_usage_api_endpoints(monkeypatch, tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'api-usage.db'}"
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    store = DatabaseModelUsageStore(database_url)
    store.record(sample_entry())
    client = TestClient(app)

    list_response = client.get("/runs/run-1/model-usage")
    summary_response = client.get("/runs/run-1/model-usage/summary")

    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == "call-1"
    assert summary_response.status_code == 200
    assert summary_response.json()["total_tokens"] == 12


def sample_entry() -> ModelCallLedgerEntry:
    return ModelCallLedgerEntry(
        id="call-1",
        project_id="project-1",
        run_id="run-1",
        workflow_task_id="task-1",
        role=ModelRole.CODE_CHANGE_ANALYSIS,
        provider=ProviderKind.LOCAL_HTTP,
        model="openai:test-model",
        endpoint_type="openai_compatible",
        base_url_host_hash="hash-only",
        status=ModelCallStatus.COMPLETED,
        started_at=datetime(2026, 6, 27, tzinfo=UTC),
        completed_at=datetime(2026, 6, 27, tzinfo=UTC),
        usage_source=TokenUsageSource.PROVIDER_REPORTED,
        usage=TokenUsageBreakdown(
            input_tokens=5,
            output_tokens=7,
            provider_reported_total_tokens=12,
        ),
    )
