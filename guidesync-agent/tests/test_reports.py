from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import SimpleNamespace

from guidesync_agent.reports import write_reports
from guidesync_agent.schemas import (
    DocumentationUpdate,
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProviderConfig,
    ProviderRunMetadata,
    RepositoryInput,
    ReviewerCheck,
)


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
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setenv("GUIDESYNC_ARTIFACT_STORAGE", "s3")
    monkeypatch.setenv("GUIDESYNC_S3_BUCKET", "guidesync-reports")
    monkeypatch.setenv("GUIDESYNC_S3_PREFIX", "reports")

    artifacts = write_reports(minimal_result())

    assert artifacts == {
        "report.md": "s3://guidesync-reports/reports/pytest-s3-run/report.md",
        "report.html": "s3://guidesync-reports/reports/pytest-s3-run/report.html",
        "run.json": "s3://guidesync-reports/reports/pytest-s3-run/run.json",
    }
    assert [write["Key"] for write in writes] == [
        "reports/pytest-s3-run/report.md",
        "reports/pytest-s3-run/report.html",
        "reports/pytest-s3-run/run.json",
    ]
