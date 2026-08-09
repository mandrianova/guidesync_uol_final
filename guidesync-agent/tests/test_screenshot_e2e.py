from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright

from guidesync_agent.reports import read_artifact, write_reports
from guidesync_agent.schemas import (
    DocumentationUpdate,
    EvidenceBundle,
    FileChangeSummary,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ReportConfig,
    RepositoryInput,
    ReviewerCheck,
    ScreenshotCaptureResult,
    ScreenshotPolicy,
    ScreenshotValidationStatus,
)
from guidesync_agent.services.screenshot_validation import (
    DeterministicScreenshotVisionAdapter,
)
from guidesync_agent.services.screenshots import (
    ScreenshotWorkflowContext,
    capture_task_screenshots,
)
from guidesync_agent.storage import create_run_store

COMPOSE_FRONTEND_URL = "http://host.docker.internal:5173/#/profile"
PUBLIC_FIXTURE_RUN_ID = "release-report-ui-e2e-20260809"


def test_compose_ui_fixture_captures_validates_and_persists_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_compose_frontend()
    configure_compose_runtime(monkeypatch)
    evidence = EvidenceBundle()
    request = GuideSyncRunRequest(
        run_id=PUBLIC_FIXTURE_RUN_ID,
        goal="Explain the project-profile workflow.",
        screenshot_policy=ScreenshotPolicy.REQUIRED,
        task_interface_url=COMPOSE_FRONTEND_URL,
        repositories=[
            RepositoryInput(
                name="guidesync-agent",
                url="https://github.com/example/guidesync-agent",
                since="2026-08-01",
                until="2026-08-09",
            )
        ],
        report=ReportConfig(
            output_dir=tmp_path / "reports",
            product_name="GuideSync",
            title="GuideSync product update",
            formats=["md", "json"],
        ),
    )
    summary = FileChangeSummary(
        id="compose-project-profile",
        repository_id="guidesync-agent",
        path="frontend/src/features/projects/ProjectProfile.tsx",
        status="modified",
        technical_summary="The project profile workflow is visible in the app shell.",
        product_impact="Project profiles are easier to review.",
        affected_workflows=["Project profile"],
        needs_screenshot_check=True,
        evidence_refs=["fixture:compose-project-profile"],
    )

    screenshots = capture_task_screenshots(
        ScreenshotWorkflowContext(
            request=request,
            evidence=evidence,
            file_summaries=[summary],
            output_dir=tmp_path / "screenshots",
        ),
        vision_adapter=DeterministicScreenshotVisionAdapter(),
    )

    assert screenshots.findings == [], [
        {
            "blank": capture.blank,
            "console_errors": capture.console_errors,
            "reasons": capture.validation_reasons,
            "title": capture.title,
            "url": capture.url,
            "visible_text": capture.visible_text,
        }
        if isinstance(capture, ScreenshotCaptureResult)
        else capture.model_dump(mode="json")
        for capture in screenshots.captures
    ]
    capture = screenshots.captures[-1]
    assert isinstance(capture, ScreenshotCaptureResult)
    assert capture.validation_status is ScreenshotValidationStatus.PASSED
    assert capture.publication_approved is True
    assert capture.policy_audit is not None
    assert capture.policy_audit.decision == "allowed"
    assert capture.dom_hash
    assert_publication_crop(capture)
    assert capture.prepared_artifact_name in screenshots.artifacts
    assert capture.raw_artifact_name in screenshots.artifacts

    result = GuideSyncRunResult(
        run_id=request.run_id,
        status="completed",
        request=request,
        evidence=evidence,
        update=DocumentationUpdate(
            title="Project profiles are easier to review",
            summary="The profile view keeps project context and documentation categories together.",
            user_facing_change="You can review the generated project brief in one clear workspace.",
            proposed_update_markdown=(
                "Open **Project profile**, then review the project structure, architecture, "
                "core concepts, and documentation categories."
            ),
            evidence_used=[],
            reviewer_checks=[
                ReviewerCheck(
                    name="Fixture review",
                    status="pass",
                    notes="Local deterministic fixture.",
                )
            ],
        ),
        artifacts=screenshots.artifacts,
    )
    result.artifacts = write_reports(result)
    create_run_store().save(result)

    publication = json.loads(read_artifact(result.artifacts["report.json"]).body)
    screenshot = publication["changes"][0]["screenshot"]
    assert screenshot["artifact_name"] == capture.prepared_artifact_name
    assert "path" not in screenshot
    prepared = read_artifact(result.artifacts[screenshot["artifact_name"]])
    assert prepared.content_type == "image/png"
    assert prepared.body.startswith(b"\x89PNG\r\n\x1a\n")
    assert_public_report_responsive_and_print(request.run_id)


def test_optional_non_ui_fixture_never_starts_browser(tmp_path: Path) -> None:
    def fail_capture(*_: object) -> dict[str, object]:
        raise AssertionError("optional non-UI fixture must not start the browser")

    result = capture_task_screenshots(
        ScreenshotWorkflowContext(
            request=GuideSyncRunRequest(
                goal="Explain parser reliability improvements.",
                screenshot_policy=ScreenshotPolicy.OPTIONAL,
                task_interface_url=COMPOSE_FRONTEND_URL,
            ),
            evidence=EvidenceBundle(),
            file_summaries=[
                FileChangeSummary(
                    repository_id="guidesync-agent",
                    path="src/guidesync_agent/services/parser.py",
                    status="modified",
                    technical_summary="Parser failures are normalized.",
                    product_impact="Invalid input produces clearer errors.",
                    needs_screenshot_check=False,
                )
            ],
            output_dir=tmp_path,
        ),
        capture_func=fail_capture,
    )

    plan = json.loads(Path(result.artifacts["screenshot-plan.json"]).read_text())
    assert plan["items"] == []
    assert result.captures == []


def require_compose_frontend() -> None:
    if os.environ.get("GUIDESYNC_RUN_COMPOSE_E2E") != "1":
        pytest.skip("Set GUIDESYNC_RUN_COMPOSE_E2E=1 for the stateful Compose fixture.")
    try:
        response = httpx.get(COMPOSE_FRONTEND_URL, timeout=3)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"Compose frontend fixture is not running: {exc}")


def configure_compose_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "GUIDESYNC_DATABASE_URL",
        "postgresql+psycopg://guidesync:guidesync@db:5432/guidesync",
    )
    monkeypatch.setenv("GUIDESYNC_ARTIFACT_STORAGE", "s3")
    monkeypatch.setenv("GUIDESYNC_S3_BUCKET", "guidesync-reports")
    monkeypatch.setenv("GUIDESYNC_S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setenv("GUIDESYNC_S3_PREFIX", "reports")


def assert_publication_crop(capture: ScreenshotCaptureResult) -> None:
    assert capture.crop is not None
    assert capture.crop.mode == "element-content"
    assert capture.crop.x is not None and capture.crop.x > 0
    assert capture.image_width is not None and capture.image_width < 1440
    assert any(
        mask.reason == "internal_identifier" and mask.locator.startswith("profile-")
        for mask in capture.masks
    )


def assert_public_report_responsive_and_print(run_id: str) -> None:
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 1600})
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(
            f"http://host.docker.internal:5173/#/reports/{run_id}/public",
            wait_until="networkidle",
        )
        page.locator("h1").wait_for()
        assert page.locator("h1").inner_text() == "GuideSync product update"
        assert page.locator("h2").first.inner_text() == "Project profiles are easier to review"
        page.set_viewport_size({"width": 390, "height": 844})
        mobile_layout = page.evaluate(
            """() => {
              const image = document.querySelector('figure img');
              const controls = Array.from(document.querySelectorAll(
                '.public-release-back, .public-release-print'
              ));
              return {
                controlsClipped: controls.some((control) => {
                  const rect = control.getBoundingClientRect();
                  return rect.left < 0 || rect.right > window.innerWidth;
                }),
                horizontalOverflow: Math.max(
                  document.body.scrollWidth,
                  document.documentElement.scrollWidth
                ) > window.innerWidth,
                imageComplete: Boolean(image && image.complete && image.naturalWidth > 0),
              };
            }"""
        )
        page.set_viewport_size({"width": 1200, "height": 1600})
        page.emulate_media(media="print")
        print_layout = page.evaluate(
            """() => ({
              backDisplay: getComputedStyle(
                document.querySelector('.public-release-back')
              ).display,
              bodyBackground: getComputedStyle(document.body).backgroundColor,
              horizontalOverflow: Math.max(
                document.body.scrollWidth,
                document.documentElement.scrollWidth
              ) > window.innerWidth,
              imageComplete: (() => {
                const image = document.querySelector('figure img');
                return Boolean(image && image.complete && image.naturalWidth > 0);
              })(),
              printDisplay: getComputedStyle(
                document.querySelector('.public-release-print')
              ).display,
              sheetShadow: getComputedStyle(
                document.querySelector('.public-release-sheet')
              ).boxShadow
            })"""
        )
        browser.close()

    assert errors == []
    assert mobile_layout == {
        "controlsClipped": False,
        "horizontalOverflow": False,
        "imageComplete": True,
    }
    assert print_layout == {
        "backDisplay": "none",
        "bodyBackground": "rgb(255, 255, 255)",
        "horizontalOverflow": False,
        "imageComplete": True,
        "printDisplay": "none",
        "sheetShadow": "none",
    }
