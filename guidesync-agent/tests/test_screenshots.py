from __future__ import annotations

from pathlib import Path
from typing import Any

from guidesync_agent.schemas import EvidenceBundle, GuideSyncRunRequest, ScreenshotPolicy
from guidesync_agent.services.screenshots import capture_task_screenshots


def test_disabled_screenshot_policy_does_not_call_capture(tmp_path: Path) -> None:
    def fail_capture(**_: Any) -> dict[str, Any]:
        raise AssertionError("capture should not be called")

    result = capture_task_screenshots(
        GuideSyncRunRequest(
            goal="Document workflow screenshots.",
            screenshot_policy=ScreenshotPolicy.DISABLED,
        ),
        EvidenceBundle(),
        [],
        output_dir=tmp_path,
        capture_func=fail_capture,
    )

    assert result.captures == []
    assert result.artifacts == {}
    assert result.findings == []


def test_required_screenshot_without_url_records_error(tmp_path: Path) -> None:
    result = capture_task_screenshots(
        GuideSyncRunRequest(
            goal="Document workflow screenshots.",
            screenshot_policy=ScreenshotPolicy.REQUIRED,
        ),
        EvidenceBundle(),
        [],
        output_dir=tmp_path,
    )

    assert result.captures == []
    assert result.artifacts["screenshot-plan.json"]
    assert any(finding.severity == "error" for finding in result.findings)


def test_successful_screenshot_capture_records_artifact_and_metadata(
    tmp_path: Path,
) -> None:
    evidence = EvidenceBundle()

    def fake_capture(**kwargs: Any) -> dict[str, Any]:
        screenshot_dir = kwargs["config"].screenshot_dir
        path = screenshot_dir / "task-interface.png"
        path.write_bytes(b"not-a-real-png-but-not-blank")
        return {
            "ok": True,
            "scenario": kwargs["scenario"],
            "url": kwargs["url"],
            "path": str(path),
            "title": "Workflow dashboard",
            "viewport": {"width": kwargs["width"], "height": kwargs["height"]},
            "visible_text": "Document workflow screenshots",
            "matched_text": ["document", "workflow"],
            "missing_text": [],
            "console_errors": [],
            "network_errors": [],
            "image_hash": "abc123",
            "blank": False,
            "ocr_text": "Document workflow screenshots",
        }

    result = capture_task_screenshots(
        GuideSyncRunRequest(
            goal="Document workflow screenshots.",
            screenshot_policy=ScreenshotPolicy.OPTIONAL,
            task_interface_url="http://127.0.0.1:5173/workflow",
        ),
        evidence,
        [],
        output_dir=tmp_path,
        capture_func=fake_capture,
    )

    assert result.findings == []
    assert result.captures[0].ocr_text == "Document workflow screenshots"
    assert result.artifacts["screenshot-results.json"]
    assert result.artifacts["task-interface.png"].endswith("task-interface.png")
    assert evidence.browser_screenshots[0].title == "Workflow dashboard"
    assert evidence.browser_screenshots[0].ocr_text == "Document workflow screenshots"
