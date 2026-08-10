from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from guidesync_agent import reports
from guidesync_agent.api import app
from guidesync_agent.config import ArtifactStorageConfig
from guidesync_agent.controllers import run_artifacts
from guidesync_agent.reports import ArtifactContent, read_artifact, write_reports
from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    DocumentationUpdate,
    DocumentationUpdateChange,
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
    publication = json.loads(read_artifact(artifacts["report.json"]).body)
    diagnostics = json.loads(read_artifact(artifacts["run.json"]).body)
    assert publication["product_name"] == "Atlas"
    assert "provider_metadata" not in publication
    assert diagnostics["provider_metadata"]["model"] == "private-model"


def test_publication_endpoint_returns_the_persisted_contract(tmp_path: Path) -> None:
    result = publication_result(tmp_path)
    result.artifacts = write_reports(result)
    create_run_store().save(result)

    report_uri = result.artifacts["report.json"]
    persisted = json.loads(read_artifact(report_uri).body)
    persisted["title"] = "Persisted publication title"
    parsed = urlparse(report_uri)
    config = reports.artifact_storage_config()
    reports.boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
    ).put_object(
        Bucket=parsed.netloc,
        Key=parsed.path.lstrip("/"),
        Body=json.dumps(persisted).encode(),
        ContentType="application/json; charset=utf-8",
    )

    response = TestClient(app).get(f"/runs/{result.run_id}/publication-report")

    assert response.status_code == 200
    assert response.json() == persisted
    assert result.update is not None
    assert response.json()["title"] != result.update.title


def test_publication_reader_uses_the_key_from_the_persisted_public_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[tuple[str, str]] = []
    monkeypatch.setattr(
        run_artifacts,
        "artifact_storage_config",
        lambda: ArtifactStorageConfig(
            bucket="guidesync-reports",
            prefix="current-prefix",
            public_base_url="https://cdn.example.com/guidesync",
        ),
    )
    monkeypatch.setattr(
        run_artifacts,
        "read_s3_artifact",
        lambda bucket, key: (
            reads.append((bucket, key))
            or ArtifactContent(body=b"{}", content_type="application/json")
        ),
    )

    run_artifacts.read_publication_artifact(
        "https://cdn.example.com/guidesync/archived-prefix/run-1/report.json"
    )

    assert reads == [
        ("guidesync-reports", "archived-prefix/run-1/report.json")
    ]
    with pytest.raises(ValueError, match="outside the configured public base URL"):
        run_artifacts.read_publication_artifact(
            "https://other.example.com/guidesync/archived-prefix/run-1/report.json"
        )


def test_publication_uses_only_prepared_screenshot_artifact(tmp_path: Path) -> None:
    result = publication_result(tmp_path)
    image_path = tmp_path / "navigation-prepared.png"
    open_image_path = tmp_path / "navigation-open-prepared.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\npublication-image")
    open_image_path.write_bytes(b"\x89PNG\r\n\x1a\nopen-publication-image")
    result.evidence.browser_screenshots.extend(
        [
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
            ),
            BrowserScreenshotEvidence(
                scenario="navigation-open",
                scenario_id="scenario-navigation-open",
                change_id="change-navigation",
                claim_id="claim-navigation-open",
                url="http://127.0.0.1:5173/#/projects",
                path=str(open_image_path),
                raw_path=str(tmp_path / "navigation-open-raw.png"),
                prepared_artifact_name=open_image_path.name,
                caption="The navigation is open.",
                alt_text="Open project navigation.",
                image_width=390,
                image_height=844,
                validation_status=ScreenshotValidationStatus.PASSED,
                publication_approved=True,
            ),
        ]
    )
    result.artifacts = {
        image_path.name: str(image_path),
        open_image_path.name: str(open_image_path),
    }

    artifacts = write_reports(result)
    publication = json.loads(read_artifact(artifacts["report.json"]).body)

    screenshots = publication["changes"][0]["screenshots"]
    assert [item["artifact_name"] for item in screenshots] == [
        image_path.name,
        open_image_path.name,
    ]
    assert all("path" not in item for item in screenshots)

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


def test_publication_groups_multiple_screenshots_by_change(tmp_path: Path) -> None:
    result = publication_result(tmp_path)
    assert result.update is not None
    result.update.changes = [
        DocumentationUpdateChange(
            id="change-navigation",
            title="Clearer navigation",
            summary="The current navigation state is easier to see.",
            user_facing_change="Users can distinguish open and closed navigation.",
            evidence_refs=["diff:repo:navigation"],
        ),
        DocumentationUpdateChange(
            id="change-search",
            title="Faster search",
            summary="Search opens from the header.",
            user_facing_change="Users can reach search from every page.",
            evidence_refs=["diff:repo:search"],
        ),
        DocumentationUpdateChange(
            id="change-copy",
            title="Clearer labels",
            summary="Labels use simpler wording.",
            user_facing_change="The updated wording is easier to scan.",
            evidence_refs=["diff:repo:copy"],
        ),
    ]
    result.evidence.browser_screenshots = [
        approved_screenshot("navigation-closed", "change-navigation"),
        approved_screenshot("navigation-open", "change-navigation"),
        approved_screenshot("search-open", "change-search"),
    ]

    report = build_publication_report(result)

    assert report is not None
    assert [change.id for change in report.changes] == [
        "change-navigation",
        "change-search",
        "change-copy",
    ]
    assert [
        [screenshot.scenario_id for screenshot in change.screenshots]
        for change in report.changes
    ] == [
        ["navigation-closed", "navigation-open"],
        ["search-open"],
        [],
    ]
    assert report.changes[2].screenshots == []
    keys = recursive_keys(report.model_dump(mode="json"))
    assert "raw_path" not in keys


def approved_screenshot(
    scenario_id: str,
    change_id: str,
) -> BrowserScreenshotEvidence:
    return BrowserScreenshotEvidence(
        scenario=scenario_id,
        scenario_id=scenario_id,
        change_id=change_id,
        claim_id=f"claim-{scenario_id}",
        url="https://example.com/guide",
        path=f"/private/{scenario_id}.png",
        raw_path=f"/private/{scenario_id}-raw.png",
        prepared_artifact_name=f"{scenario_id}.png",
        caption=f"{scenario_id} caption",
        alt_text=f"{scenario_id} alt text",
        image_width=390,
        image_height=844,
        validation_status=ScreenshotValidationStatus.PASSED,
        publication_approved=True,
    )


def recursive_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key) for key in value}
        return keys.union(*(recursive_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(recursive_keys(item) for item in value))
    return set()
