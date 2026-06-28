from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from storage_test_utils import sqlite_database_url

from guidesync_agent.schemas import (
    EvidenceBundle,
    GuideSyncRunRequest,
    ModelRole,
    ProviderKind,
    ScreenshotCaptureResult,
    ScreenshotPolicy,
    ScreenshotValidationStatus,
    ScreenshotVisionResult,
    TokenUsageSource,
)
from guidesync_agent.services.screenshots import capture_task_screenshots
from guidesync_agent.storage import DatabaseModelUsageStore


class FakeVisionAdapter:
    name = "fake-ocr"

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts

    def extract_text(self, capture: ScreenshotCaptureResult) -> ScreenshotVisionResult:
        text = self.texts[min(capture.attempt - 1, len(self.texts) - 1)]
        return ScreenshotVisionResult(adapter=self.name, text=text)


class FakeUsageVisionAdapter:
    name = "fake-usage-vision"

    def extract_text(self, capture: ScreenshotCaptureResult) -> ScreenshotVisionResult:
        started = datetime(2026, 6, 27, tzinfo=UTC)
        completed = datetime(2026, 6, 27, 0, 0, 1, tzinfo=UTC)
        return ScreenshotVisionResult(
            adapter=self.name,
            text=capture.visible_text,
            role=ModelRole.SCREENSHOT_VISION,
            provider=ProviderKind.LOCAL_HTTP.value,
            model="openai:vision-model",
            model_metadata={
                "model_call_attempted": True,
                "started_at": started.isoformat(),
                "completed_at": completed.isoformat(),
                "latency_ms": 1000,
                "prompt_tokens": 20,
                "completion_tokens": 8,
                "total_tokens": 28,
                "image_input_units": 1,
                "base_url_host_hash": "vision-host-hash",
            },
        )


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
    assert result.captures[0].validation_status == ScreenshotValidationStatus.PASSED
    assert result.artifacts["screenshot-results.json"]
    assert result.artifacts["task-interface.png"].endswith("task-interface.png")
    assert evidence.browser_screenshots[0].title == "Workflow dashboard"
    assert evidence.browser_screenshots[0].ocr_text == "Document workflow screenshots"
    assert evidence.browser_screenshots[0].validation_status == ScreenshotValidationStatus.PASSED


def test_screenshot_vision_records_model_usage(monkeypatch, tmp_path: Path) -> None:
    database_url = sqlite_database_url(tmp_path / "screenshot-usage.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)

    def fake_capture(**kwargs: Any) -> dict[str, Any]:
        path = kwargs["config"].screenshot_dir / "task-interface.png"
        path.write_bytes(b"not-blank")
        return {
            "ok": True,
            "scenario": kwargs["scenario"],
            "url": kwargs["url"],
            "path": str(path),
            "visible_text": "Document workflow screenshots",
            "blank": False,
        }

    result = capture_task_screenshots(
        GuideSyncRunRequest(
            run_id="run-screenshot-usage",
            goal="Document workflow screenshots.",
            screenshot_policy=ScreenshotPolicy.OPTIONAL,
            task_interface_url="http://127.0.0.1:5173/workflow",
        ),
        EvidenceBundle(),
        [],
        output_dir=tmp_path,
        capture_func=fake_capture,
        vision_adapter=FakeUsageVisionAdapter(),
        workflow_task_id="workflow-screenshot-1",
    )

    entries = DatabaseModelUsageStore(database_url).list_for_run("run-screenshot-usage")
    assert result.findings == []
    assert len(entries) == 1
    assert entries[0].role == ModelRole.SCREENSHOT_VISION
    assert entries[0].workflow_task_id == "workflow-screenshot-1"
    assert entries[0].provider == ProviderKind.LOCAL_HTTP
    assert entries[0].model == "openai:vision-model"
    assert entries[0].base_url_host_hash == "vision-host-hash"
    assert entries[0].usage_source == TokenUsageSource.PROVIDER_REPORTED
    assert entries[0].usage.input_tokens == 20
    assert entries[0].usage.output_tokens == 8
    assert entries[0].usage.provider_reported_total_tokens == 28
    assert entries[0].usage.image_input_units == 1


def test_screenshot_validation_reports_ocr_mismatch(tmp_path: Path) -> None:
    def fake_capture(**kwargs: Any) -> dict[str, Any]:
        path = kwargs["config"].screenshot_dir / "task-interface.png"
        path.write_bytes(b"not-blank")
        return {
            "ok": True,
            "scenario": kwargs["scenario"],
            "url": kwargs["url"],
            "path": str(path),
            "visible_text": "Document workflow screenshots",
            "blank": False,
        }

    result = capture_task_screenshots(
        GuideSyncRunRequest(
            goal="Document workflow screenshots.",
            screenshot_policy=ScreenshotPolicy.REQUIRED,
            task_interface_url="http://127.0.0.1:5173/workflow",
        ),
        EvidenceBundle(),
        [],
        output_dir=tmp_path,
        capture_func=fake_capture,
        vision_adapter=FakeVisionAdapter(["Wrong page"]),
    )

    assert len(result.captures) == 1
    assert result.captures[0].validation_status == ScreenshotValidationStatus.FAILED
    assert result.captures[0].validation_reasons == ["ocr_missing_expected_text"]
    assert any(finding.check == "screenshot.validation" for finding in result.findings)


def test_required_screenshot_retries_blank_capture(tmp_path: Path) -> None:
    evidence = EvidenceBundle()

    def fake_capture(**kwargs: Any) -> dict[str, Any]:
        path = kwargs["config"].screenshot_dir / f"task-interface-{kwargs['attempt']}.png"
        path.write_bytes(b"not-blank")
        if kwargs["attempt"] == 1:
            return {
                "ok": True,
                "scenario": kwargs["scenario"],
                "url": kwargs["url"],
                "path": str(path),
                "visible_text": "",
                "blank": True,
            }
        return {
            "ok": True,
            "scenario": kwargs["scenario"],
            "url": kwargs["url"],
            "path": str(path),
            "visible_text": "Document workflow screenshots",
            "blank": False,
        }

    result = capture_task_screenshots(
        GuideSyncRunRequest(
            goal="Document workflow screenshots.",
            screenshot_policy=ScreenshotPolicy.REQUIRED,
            task_interface_url="http://127.0.0.1:5173/workflow",
        ),
        evidence,
        [],
        output_dir=tmp_path,
        capture_func=fake_capture,
        vision_adapter=FakeVisionAdapter(["", "Document workflow screenshots"]),
    )

    assert result.findings == []
    assert len(result.captures) == 2
    assert result.captures[0].validation_status == ScreenshotValidationStatus.FAILED
    assert result.captures[1].validation_status == ScreenshotValidationStatus.PASSED
    assert len(result.captures[1].validation_attempts) == 2
    assert evidence.browser_screenshots[0].attempts == 2


def test_required_screenshot_failure_after_retry_is_blocking(tmp_path: Path) -> None:
    def fake_capture(**kwargs: Any) -> dict[str, Any]:
        path = kwargs["config"].screenshot_dir / f"task-interface-{kwargs['attempt']}.png"
        path.write_bytes(b"not-blank")
        return {
            "ok": True,
            "scenario": kwargs["scenario"],
            "url": kwargs["url"],
            "path": str(path),
            "visible_text": "Wrong page",
            "blank": False,
        }

    result = capture_task_screenshots(
        GuideSyncRunRequest(
            goal="Document workflow screenshots.",
            screenshot_policy=ScreenshotPolicy.REQUIRED,
            task_interface_url="http://127.0.0.1:5173/workflow",
        ),
        EvidenceBundle(),
        [],
        output_dir=tmp_path,
        capture_func=fake_capture,
        vision_adapter=FakeVisionAdapter(["Wrong page", "Wrong page"]),
    )

    assert len(result.captures) == 2
    assert result.captures[-1].validation_status == ScreenshotValidationStatus.FAILED
    assert any(
        finding.severity == "error" and finding.check == "screenshot.validation"
        for finding in result.findings
    )
