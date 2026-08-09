from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError
from storage_test_utils import sqlite_database_url

from guidesync_agent import reports
from guidesync_agent.reports import read_artifact, render_markdown, write_reports
from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    DocumentationEditResult,
    DocumentationUpdate,
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ModelCallLedgerEntry,
    ModelCallStatus,
    ModelRole,
    ProviderConfig,
    ProviderKind,
    ProviderRunMetadata,
    RepositoryInput,
    ReviewerCheck,
    ScreenshotValidationStatus,
    TokenUsageBreakdown,
    TokenUsageSource,
)
from guidesync_agent.storage import DatabaseModelUsageStore


def minimal_result() -> GuideSyncRunResult:
    request = GuideSyncRunRequest(
        run_id="pytest-s3-run",
        goal="Create report artifacts.",
        provider=ProviderConfig(),
        repositories=[RepositoryInput(name="repo", url="https://github.com/example/repo")],
    )
    return GuideSyncRunResult(
        run_id=request.run_id,
        status="completed",
        request=request,
        evidence=EvidenceBundle(),
        update=DocumentationUpdate(
            title="Report title",
            summary="Summary",
            user_facing_change="Change",
            proposed_update_markdown="Body",
            evidence_used=[],
            reviewer_checks=[ReviewerCheck(name="Review", status="required", notes="Check")],
        ),
        provider_metadata=ProviderRunMetadata(
            provider="mock",
            model="mock:deterministic",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            latency_ms=1,
        ),
    )


def test_write_reports_to_s3(monkeypatch) -> None:
    writes = []

    class FakeClient:
        def put_object(self, **kwargs) -> None:
            writes.append(kwargs)

    fake_boto3 = SimpleNamespace(client=lambda *_, **__: FakeClient())
    monkeypatch.setattr(reports, "boto3", fake_boto3)
    monkeypatch.setenv("GUIDESYNC_S3_BUCKET", "guidesync-reports")
    monkeypatch.setenv("GUIDESYNC_S3_PREFIX", "reports")

    artifacts = write_reports(minimal_result())

    assert artifacts == {
        "technical-report.md": (
            "s3://guidesync-reports/reports/pytest-s3-run/technical-report.md"
        ),
        "report.json": "s3://guidesync-reports/reports/pytest-s3-run/report.json",
        "run.json": "s3://guidesync-reports/reports/pytest-s3-run/run.json",
    }
    assert [write["Key"] for write in writes] == [
        "reports/pytest-s3-run/technical-report.md",
        "reports/pytest-s3-run/report.json",
        "reports/pytest-s3-run/run.json",
    ]


def test_write_reports_to_s3_uploads_existing_workflow_artifacts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    writes = []

    class FakeClient:
        def put_object(self, **kwargs) -> None:
            writes.append(kwargs)

    fake_boto3 = SimpleNamespace(client=lambda *_, **__: FakeClient())
    monkeypatch.setattr(reports, "boto3", fake_boto3)
    monkeypatch.setenv("GUIDESYNC_S3_BUCKET", "guidesync-reports")
    monkeypatch.setenv("GUIDESYNC_S3_PREFIX", "reports")

    patch_path = tmp_path / "documentation.patch"
    patch_path.write_text("diff --git a/docs/guide.md b/docs/guide.md\n", encoding="utf-8")
    result = minimal_result()
    result.artifacts = {"documentation.patch": str(patch_path)}

    artifacts = write_reports(result)

    assert artifacts["documentation.patch"] == (
        "s3://guidesync-reports/reports/pytest-s3-run/documentation.patch"
    )
    assert [write["Key"] for write in writes] == [
        "reports/pytest-s3-run/documentation.patch",
        "reports/pytest-s3-run/technical-report.md",
        "reports/pytest-s3-run/report.json",
        "reports/pytest-s3-run/run.json",
    ]
    run_json = next(write for write in writes if write["Key"].endswith("/run.json"))
    payload = json.loads(run_json["Body"])
    assert payload["artifacts"]["documentation.patch"] == artifacts["documentation.patch"]


def test_read_s3_artifact_normalizes_missing_objects(monkeypatch) -> None:
    class FakeClient:
        def get_object(self, **_kwargs) -> None:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            )

    monkeypatch.setattr(
        reports,
        "boto3",
        SimpleNamespace(client=lambda *_, **__: FakeClient()),
    )

    with pytest.raises(FileNotFoundError, match=r"missing/report\.json"):
        reports.read_s3_artifact("guidesync-reports", "missing/report.json")


def test_read_artifact_rejects_file_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must use s3"):
        read_artifact(str(tmp_path / "report.json"))


def test_markdown_report_includes_inspection_sections() -> None:
    result = minimal_result()
    assert result.update is not None
    result.update.documentation_edit = DocumentationEditResult(
        repository_id="repo-docs",
        docs_path="docs",
        target_path="docs/guide.md",
        changed_docs=["docs/guide.md"],
        updated_docs=["docs/guide.md"],
        commit_sha="abc1234",
        knowledge_index_run_id="kg-run",
    )
    result.evidence.browser_screenshots.append(
        BrowserScreenshotEvidence(
            scenario="task-interface",
            url="http://127.0.0.1:5173",
            path="/tmp/screenshot.png",
            title="GuideSync",
            image_hash="hash123",
            validation_status=ScreenshotValidationStatus.FAILED,
            validation_reasons=["ocr_missing_expected_text"],
            attempts=2,
        )
    )
    result.artifacts = {
        "documentation.patch": "/tmp/documentation.patch",
        "file-summaries.json": "/tmp/file-summaries.json",
    }

    markdown = render_markdown(result)

    assert "## Documentation Edit" in markdown
    assert "## Screenshots" in markdown
    assert "Validation: `failed`" in markdown
    assert "Attempts: 2" in markdown
    assert "## Artifacts" in markdown
    assert "documentation.patch" in markdown


def test_reports_include_token_usage_summary(monkeypatch, tmp_path: Path) -> None:
    database_url = sqlite_database_url(tmp_path / "report-usage.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    result = minimal_result()
    result.request.report.output_dir = tmp_path / "reports"
    DatabaseModelUsageStore(database_url).record(
        ModelCallLedgerEntry(
            id="report-call-1",
            run_id=result.run_id,
            workflow_task_id="workflow-report-1",
            role=ModelRole.ORCHESTRATOR,
            provider=ProviderKind.LOCAL_HTTP,
            model="openai:test-model",
            status=ModelCallStatus.COMPLETED,
            started_at=datetime(2026, 6, 27, tzinfo=UTC),
            completed_at=datetime(2026, 6, 27, tzinfo=UTC),
            usage_source=TokenUsageSource.PROVIDER_REPORTED,
            usage=TokenUsageBreakdown(
                input_tokens=8,
                output_tokens=4,
                provider_reported_total_tokens=12,
            ),
        )
    )

    markdown = render_markdown(result)
    artifacts = write_reports(result)
    payload = json.loads(read_artifact(artifacts["run.json"]).body)

    assert "## Token Usage" in markdown
    assert "Total tokens: `12`" in markdown
    assert payload["token_usage_summary"]["total_tokens"] == 12
    assert payload["token_usage_summary"]["by_workflow_task"][0]["key"] == "workflow-report-1"
