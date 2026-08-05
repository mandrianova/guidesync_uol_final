from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from storage_test_utils import sqlite_database_url

from guidesync_agent.schemas import (
    EvidenceBundle,
    GuideSyncRunRequest,
    ModelRole,
    OperationError,
    ProviderKind,
    ScreenshotCaptureFailure,
    ScreenshotCaptureResult,
    ScreenshotPolicy,
    ScreenshotValidationStatus,
    ScreenshotVisionResult,
    TokenUsageSource,
)
from guidesync_agent.services.screenshots import (
    ScreenshotWorkflowContext,
    capture_task_screenshots,
)
from guidesync_agent.storage import DatabaseModelUsageStore
from guidesync_agent.tools.browser import (
    BrowserCaptureContext,
    BrowserCaptureDiagnostics,
    BrowserToolConfig,
    capture_browser_screenshot,
    dump_browser_capture,
    record_screenshot,
)
from guidesync_agent.tools.browser_models import BrowserScreenshotRequest


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


def screenshot_context(
    request: GuideSyncRunRequest,
    output_dir: Path,
    *,
    evidence: EvidenceBundle | None = None,
    workflow_task_id: str | None = None,
) -> ScreenshotWorkflowContext:
    return ScreenshotWorkflowContext(
        request=request,
        evidence=evidence or EvidenceBundle(),
        file_summaries=[],
        output_dir=output_dir,
        workflow_task_id=workflow_task_id,
    )


def test_disabled_screenshot_policy_does_not_call_capture(tmp_path: Path) -> None:
    def fail_capture(*_: Any) -> dict[str, Any]:
        raise AssertionError("capture should not be called")

    result = capture_task_screenshots(
        screenshot_context(
            GuideSyncRunRequest(
                goal="Document workflow screenshots.",
                screenshot_policy=ScreenshotPolicy.DISABLED,
            ),
            tmp_path,
        ),
        capture_func=fail_capture,
    )

    assert result.captures == []
    assert result.artifacts == {}
    assert result.findings == []


def test_required_screenshot_without_url_records_error(tmp_path: Path) -> None:
    result = capture_task_screenshots(
        screenshot_context(
            GuideSyncRunRequest(
                goal="Document workflow screenshots.",
                screenshot_policy=ScreenshotPolicy.REQUIRED,
            ),
            tmp_path,
        ),
    )

    assert result.captures == []
    assert result.artifacts["screenshot-plan.json"]
    assert any(finding.severity == "error" for finding in result.findings)


def test_browser_capture_failure_is_structured_without_ok(tmp_path: Path) -> None:
    result = capture_browser_screenshot(
        BrowserToolConfig(enabled=False, screenshot_dir=tmp_path),
        EvidenceBundle(),
        BrowserScreenshotRequest(
            scenario="task-interface",
            url="http://127.0.0.1:5173/workflow",
            width=1440,
            height=1000,
        ),
    )

    assert "ok" not in result
    assert result["error"] == {
        "code": "browser_disabled",
        "message": "Browser screenshot tool is disabled.",
        "retryable": False,
    }


def test_recorded_screenshot_uses_model_dump_without_ok(tmp_path: Path) -> None:
    path = tmp_path / "task-interface.png"
    path.write_bytes(b"not-a-real-png-but-not-blank")
    evidence = EvidenceBundle()
    screenshot = record_screenshot(
        BrowserCaptureContext(
            evidence=evidence,
            scenario="task-interface",
            target_url="http://127.0.0.1:5173/workflow",
            path=path,
            steps=[],
            width=1440,
            height=1000,
            timeout_ms=15000,
            expected_text=["workflow"],
        ),
        BrowserCaptureDiagnostics(
            notes="Captured in test.",
            visible_text="Document workflow",
        ),
    )

    result = dump_browser_capture(screenshot)

    assert "ok" not in result
    assert result == screenshot.model_dump(mode="json")
    assert evidence.browser_screenshots == [screenshot]


def test_successful_screenshot_capture_records_artifact_and_metadata(
    tmp_path: Path,
) -> None:
    evidence = EvidenceBundle()

    def fake_capture(
        config: BrowserToolConfig,
        _: EvidenceBundle,
        request: BrowserScreenshotRequest,
    ) -> dict[str, Any]:
        path = config.screenshot_dir / "task-interface.png"
        path.write_bytes(b"not-a-real-png-but-not-blank")
        return {
            "scenario": request.scenario,
            "url": request.url,
            "path": str(path),
            "title": "Workflow dashboard",
            "viewport": {"width": request.width, "height": request.height},
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
        screenshot_context(
            GuideSyncRunRequest(
                goal="Document workflow screenshots.",
                screenshot_policy=ScreenshotPolicy.OPTIONAL,
                task_interface_url="http://127.0.0.1:5173/workflow",
            ),
            tmp_path,
            evidence=evidence,
        ),
        capture_func=fake_capture,
    )

    assert result.findings == []
    capture = result.captures[0]
    assert isinstance(capture, ScreenshotCaptureResult)
    assert capture.ocr_text == "Document workflow screenshots"
    assert capture.validation_status == ScreenshotValidationStatus.PASSED
    assert result.artifacts["screenshot-results.json"]
    assert '"ok"' not in Path(result.artifacts["screenshot-results.json"]).read_text()
    assert result.artifacts["task-interface.png"].endswith("task-interface.png")
    assert evidence.browser_screenshots[0].title == "Workflow dashboard"
    assert evidence.browser_screenshots[0].ocr_text == "Document workflow screenshots"
    assert evidence.browser_screenshots[0].validation_status == ScreenshotValidationStatus.PASSED


def test_screenshot_vision_records_model_usage(monkeypatch, tmp_path: Path) -> None:
    database_url = sqlite_database_url(tmp_path / "screenshot-usage.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)

    def fake_capture(
        config: BrowserToolConfig,
        _: EvidenceBundle,
        request: BrowserScreenshotRequest,
    ) -> dict[str, Any]:
        path = config.screenshot_dir / "task-interface.png"
        path.write_bytes(b"not-blank")
        return {
            "scenario": request.scenario,
            "url": request.url,
            "path": str(path),
            "visible_text": "Document workflow screenshots",
            "blank": False,
        }

    result = capture_task_screenshots(
        screenshot_context(
            GuideSyncRunRequest(
                run_id="run-screenshot-usage",
                goal="Document workflow screenshots.",
                screenshot_policy=ScreenshotPolicy.OPTIONAL,
                task_interface_url="http://127.0.0.1:5173/workflow",
            ),
            tmp_path,
            workflow_task_id="workflow-screenshot-1",
        ),
        capture_func=fake_capture,
        vision_adapter=FakeUsageVisionAdapter(),
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
    def fake_capture(
        config: BrowserToolConfig,
        _: EvidenceBundle,
        request: BrowserScreenshotRequest,
    ) -> dict[str, Any]:
        path = config.screenshot_dir / "task-interface.png"
        path.write_bytes(b"not-blank")
        return {
            "scenario": request.scenario,
            "url": request.url,
            "path": str(path),
            "visible_text": "Document workflow screenshots",
            "blank": False,
        }

    result = capture_task_screenshots(
        screenshot_context(
            GuideSyncRunRequest(
                goal="Document workflow screenshots.",
                screenshot_policy=ScreenshotPolicy.REQUIRED,
                task_interface_url="http://127.0.0.1:5173/workflow",
            ),
            tmp_path,
        ),
        capture_func=fake_capture,
        vision_adapter=FakeVisionAdapter(["Wrong page"]),
    )

    assert len(result.captures) == 1
    capture = result.captures[0]
    assert isinstance(capture, ScreenshotCaptureResult)
    assert capture.validation_status == ScreenshotValidationStatus.FAILED
    assert capture.validation_reasons == ["ocr_missing_expected_text"]
    assert any(finding.check == "screenshot.validation" for finding in result.findings)


def test_required_screenshot_retries_blank_capture(tmp_path: Path) -> None:
    evidence = EvidenceBundle()

    def fake_capture(
        config: BrowserToolConfig,
        _: EvidenceBundle,
        request: BrowserScreenshotRequest,
    ) -> dict[str, Any]:
        path = config.screenshot_dir / f"task-interface-{request.attempt}.png"
        path.write_bytes(b"not-blank")
        if request.attempt == 1:
            return {
                "scenario": request.scenario,
                "url": request.url,
                "path": str(path),
                "visible_text": "",
                "blank": True,
            }
        return {
            "scenario": request.scenario,
            "url": request.url,
            "path": str(path),
            "visible_text": "Document workflow screenshots",
            "blank": False,
        }

    result = capture_task_screenshots(
        screenshot_context(
            GuideSyncRunRequest(
                goal="Document workflow screenshots.",
                screenshot_policy=ScreenshotPolicy.REQUIRED,
                task_interface_url="http://127.0.0.1:5173/workflow",
            ),
            tmp_path,
            evidence=evidence,
        ),
        capture_func=fake_capture,
        vision_adapter=FakeVisionAdapter(["", "Document workflow screenshots"]),
    )

    assert result.findings == []
    assert len(result.captures) == 2
    first_capture, final_capture = result.captures
    assert isinstance(first_capture, ScreenshotCaptureResult)
    assert isinstance(final_capture, ScreenshotCaptureResult)
    assert first_capture.validation_status == ScreenshotValidationStatus.FAILED
    assert final_capture.validation_status == ScreenshotValidationStatus.PASSED
    assert len(final_capture.validation_attempts) == 2
    assert evidence.browser_screenshots[0].attempts == 2


def test_required_screenshot_failure_after_retry_is_blocking(tmp_path: Path) -> None:
    def fake_capture(
        config: BrowserToolConfig,
        _: EvidenceBundle,
        request: BrowserScreenshotRequest,
    ) -> dict[str, Any]:
        path = config.screenshot_dir / f"task-interface-{request.attempt}.png"
        path.write_bytes(b"not-blank")
        return {
            "scenario": request.scenario,
            "url": request.url,
            "path": str(path),
            "visible_text": "Wrong page",
            "blank": False,
        }

    result = capture_task_screenshots(
        screenshot_context(
            GuideSyncRunRequest(
                goal="Document workflow screenshots.",
                screenshot_policy=ScreenshotPolicy.REQUIRED,
                task_interface_url="http://127.0.0.1:5173/workflow",
            ),
            tmp_path,
        ),
        capture_func=fake_capture,
        vision_adapter=FakeVisionAdapter(["Wrong page", "Wrong page"]),
    )

    assert len(result.captures) == 2
    capture = result.captures[-1]
    assert isinstance(capture, ScreenshotCaptureResult)
    assert capture.validation_status == ScreenshotValidationStatus.FAILED
    assert any(
        finding.severity == "error" and finding.check == "screenshot.validation"
        for finding in result.findings
    )


def test_capture_failure_retries_without_calling_vision(tmp_path: Path) -> None:
    class FailVisionAdapter:
        name = "must-not-run"

        def extract_text(self, capture: ScreenshotCaptureResult) -> ScreenshotVisionResult:
            raise AssertionError(f"vision should not receive capture: {capture}")

    def fake_capture(
        _: BrowserToolConfig,
        _evidence: EvidenceBundle,
        request: BrowserScreenshotRequest,
    ) -> dict[str, Any]:
        assert request.url is not None
        failure = ScreenshotCaptureFailure(
            scenario=request.scenario,
            url=request.url,
            attempt=request.attempt,
            error=OperationError(
                code="browser_unavailable",
                message="No browser available.",
            ),
        )
        return failure.model_dump(
            mode="json",
            exclude={"scenario", "url", "attempt", "created_at"},
        )

    result = capture_task_screenshots(
        screenshot_context(
            GuideSyncRunRequest(
                goal="Document workflow screenshots.",
                screenshot_policy=ScreenshotPolicy.REQUIRED,
                task_interface_url="http://127.0.0.1:5173/workflow",
            ),
            tmp_path,
        ),
        capture_func=fake_capture,
        vision_adapter=FailVisionAdapter(),
    )

    assert len(result.captures) == 2
    assert all(isinstance(item, ScreenshotCaptureFailure) for item in result.captures)
    assert result.findings[-1].check == "screenshot.capture"
    assert result.findings[-1].message == "No browser available."
