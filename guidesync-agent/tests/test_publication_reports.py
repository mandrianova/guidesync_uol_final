from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from guidesync_agent.api import app
from guidesync_agent.reports import write_reports
from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    DocumentationUpdate,
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProviderConfig,
    ProviderRunMetadata,
    ReportConfig,
    ReportLocale,
    RepositoryInput,
    ReviewerCheck,
    ScreenshotValidationStatus,
    ValidationFinding,
)
from guidesync_agent.services.publication_reports import build_publication_report
from guidesync_agent.storage import create_run_store

TECHNICAL_KEYS = {
    "run_id",
    "provider",
    "model",
    "token_usage",
    "transcript_id",
    "path",
    "diff",
    "findings",
}


def publication_result(tmp_path: Path) -> GuideSyncRunResult:
    request = GuideSyncRunRequest(
        run_id="pytest-publication-run",
        goal="Explain the user-visible navigation update.",
        provider=ProviderConfig(),
        repositories=[
            RepositoryInput(
                name="web-app",
                url="https://github.com/example/web-app",
                since="2026-08-01",
                until="2026-08-09",
            )
        ],
        report=ReportConfig(
            output_dir=tmp_path / "reports",
            product_name="Atlas",
            title="Atlas product update",
            locale=ReportLocale.ENGLISH,
            formats=["md", "json"],
        ),
    )
    return GuideSyncRunResult(
        run_id=request.run_id,
        status="completed",
        request=request,
        evidence=EvidenceBundle(),
        update=DocumentationUpdate(
            title="Find recent work faster",
            summary="The updated navigation keeps recent projects one click away.",
            user_facing_change="Recent projects now stay visible while you browse.",
            proposed_update_markdown=(
                "Open **Projects**, then choose an item from the new Recent section."
            ),
            evidence_used=[],
            reviewer_checks=[
                ReviewerCheck(name="Review", status="required", notes="Check wording.")
            ],
        ),
        provider_metadata=ProviderRunMetadata(
            provider="local_http",
            model="private-model",
            started_at=datetime(2026, 8, 9, tzinfo=UTC),
            completed_at=datetime(2026, 8, 9, tzinfo=UTC),
            latency_ms=420,
            token_usage={"total": 999},
        ),
        findings=[
            ValidationFinding(
                severity="warning",
                check="reviewer-diagnostics",
                message="Internal reviewer note.",
            )
        ],
    )


def test_publication_contract_separates_user_content_from_diagnostics(
    tmp_path: Path,
) -> None:
    report = build_publication_report(publication_result(tmp_path))

    assert report is not None
    assert report.schema_version == "1.0"
    assert report.product_name == "Atlas"
    assert report.title == "Atlas product update"
    assert report.locale == ReportLocale.ENGLISH
    assert report.release_period == "2026-08-01 — 2026-08-09"
    assert report.spotlight_change_id == report.changes[0].id
    assert report.changes[0].title == "Find recent work faster"
    assert report.title != report.changes[0].title
    assert report.changes[0].how_to_markdown.startswith("Open **Projects**")

    keys = recursive_keys(report.model_dump(mode="json"))
    assert keys.isdisjoint(TECHNICAL_KEYS)


def test_write_reports_persists_publication_and_technical_artifacts(
    tmp_path: Path,
) -> None:
    result = publication_result(tmp_path)

    artifacts = write_reports(result)

    assert set(artifacts) == {"report.json", "run.json", "technical-report.md"}
    publication = json.loads(Path(artifacts["report.json"]).read_text(encoding="utf-8"))
    diagnostics = json.loads(Path(artifacts["run.json"]).read_text(encoding="utf-8"))
    assert publication["product_name"] == "Atlas"
    assert "provider_metadata" not in publication
    assert diagnostics["provider_metadata"]["model"] == "private-model"


def test_publication_endpoint_returns_the_persisted_contract(tmp_path: Path) -> None:
    result = publication_result(tmp_path)
    result.artifacts = write_reports(result)
    create_run_store().save(result)

    report_path = Path(result.artifacts["report.json"])
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    persisted["title"] = "Persisted publication title"
    report_path.write_text(json.dumps(persisted), encoding="utf-8")

    response = TestClient(app).get(f"/runs/{result.run_id}/publication-report")

    assert response.status_code == 200
    assert response.json() == persisted
    assert result.update is not None
    assert response.json()["title"] != result.update.title


def test_publication_uses_only_prepared_screenshot_artifact(tmp_path: Path) -> None:
    result = publication_result(tmp_path)
    image_path = tmp_path / "navigation-prepared.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\npublication-image")
    result.evidence.browser_screenshots.append(
        BrowserScreenshotEvidence(
            scenario="navigation",
            scenario_id="scenario-navigation",
            change_id="change-navigation",
            claim_id="claim-navigation",
            url="http://127.0.0.1:5173/#/projects",
            path=str(image_path),
            raw_path=str(tmp_path / "navigation-raw.png"),
            prepared_artifact_name=image_path.name,
            caption="Recent projects remain visible.",
            alt_text="Updated project navigation.",
            image_width=1440,
            image_height=900,
            validation_status=ScreenshotValidationStatus.PASSED,
            publication_approved=True,
        )
    )
    result.artifacts = {image_path.name: str(image_path)}

    artifacts = write_reports(result)
    publication = json.loads(Path(artifacts["report.json"]).read_text())

    screenshot = publication["changes"][0]["screenshot"]
    assert screenshot["artifact_name"] == image_path.name
    assert "path" not in screenshot

    result.artifacts = artifacts
    create_run_store().save(result)
    response = TestClient(app).get(
        f"/runs/{result.run_id}/artifacts/{image_path.name}"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"] == (
        'inline; filename="navigation-prepared.png"'
    )


def recursive_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key) for key in value}
        return keys.union(*(recursive_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(recursive_keys(item) for item in value))
    return set()
