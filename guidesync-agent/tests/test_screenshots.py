from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from storage_test_utils import sqlite_database_url

from guidesync_agent.pipeline import run as pipeline_run
from guidesync_agent.schemas import (
    EvidenceBundle,
    FileChangeSummary,
    GuideSyncRunRequest,
    ModelRole,
    OperationError,
    ProviderKind,
    ReportLocale,
    ScreenshotAction,
    ScreenshotActionKind,
    ScreenshotCaptureFailure,
    ScreenshotCaptureResult,
    ScreenshotLocatorKind,
    ScreenshotPlanItem,
    ScreenshotPolicy,
    ScreenshotValidationStatus,
    ScreenshotVisionResult,
    TokenUsageSource,
)
from guidesync_agent.services.screenshot_planning import build_screenshot_plan
from guidesync_agent.services.screenshots import (
    ScreenshotWorkflowContext,
    ScreenshotWorkflowResult,
    browser_steps_for_plan_item,
    capture_task_screenshots,
)
from guidesync_agent.storage import DatabaseModelUsageStore
from guidesync_agent.tools.browser import (
    BrowserToolConfig,
    capture_browser_screenshot,
)
from guidesync_agent.tools.browser_evidence import (
    dump_browser_capture,
    record_screenshot,
)
from guidesync_agent.tools.browser_models import (
    BrowserCaptureContext,
    BrowserCaptureDiagnostics,
    BrowserScreenshotRequest,
)
from guidesync_agent.tools.browser_support import (
    bounded_content_clip,
    ensure_allowed_page_origin,
    parse_browser_step,
    privacy_mask_targets,
    privacy_mask_values,
    screenshot_actions_for_steps,
)
from guidesync_agent.workflows.documentation_update import DocumentationUpdateWorkflowContext


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
    file_summaries: list[FileChangeSummary] | None = None,
) -> ScreenshotWorkflowContext:
    return ScreenshotWorkflowContext(
        request=request,
        evidence=evidence or EvidenceBundle(),
        file_summaries=file_summaries or [],
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


def test_async_run_offloads_sync_playwright_capture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    called = []

    def fake_capture(_: ScreenshotWorkflowContext) -> ScreenshotWorkflowResult:
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        called.append(True)
        return ScreenshotWorkflowResult()

    monkeypatch.setattr(pipeline_run, "capture_task_screenshots", fake_capture)
    request = GuideSyncRunRequest(
        goal="Capture the mobile menu.",
        screenshot_policy=ScreenshotPolicy.REQUIRED,
        task_interface_url="https://starlight.astro.build/",
    )

    context = asyncio.run(
        pipeline_run.prepare_run_workflow_context(
            request,
            EvidenceBundle(),
            DocumentationUpdateWorkflowContext(),
            workflow_task_id=None,
        )
    )

    assert called == [True]
    assert context.artifacts == {}


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
    assert result["policy_audit"]["decision"] == "denied"


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


def test_optional_non_ui_change_writes_empty_plan_without_browser(tmp_path: Path) -> None:
    summary = FileChangeSummary(
        repository_id="repo-1",
        path="src/parser.py",
        status="modified",
        technical_summary="Refined parser error handling.",
        product_impact="Errors are reported more consistently.",
        needs_screenshot_check=False,
    )

    def fail_capture(*_: Any) -> dict[str, Any]:
        raise AssertionError("non-UI optional change must not launch a browser")

    result = capture_task_screenshots(
        screenshot_context(
            GuideSyncRunRequest(
                goal="Explain parser reliability improvements.",
                screenshot_policy=ScreenshotPolicy.OPTIONAL,
                task_interface_url="http://127.0.0.1:5173/",
            ),
            tmp_path,
            file_summaries=[summary],
        ),
        capture_func=fail_capture,
    )

    plan = json.loads(Path(result.artifacts["screenshot-plan.json"]).read_text())
    assert plan["items"] == []
    assert result.captures == []
    assert result.findings == []


def test_ui_change_builds_multiple_stable_scenarios_and_prepared_artifacts(
    tmp_path: Path,
) -> None:
    summary = FileChangeSummary(
        id="summary-navigation",
        repository_id="repo-1",
        path="frontend/navigation.tsx",
        status="modified",
        technical_summary="Changed navigation and project switcher.",
        product_impact="Recent projects stay visible while users browse.",
        affected_workflows=["Recent projects", "Project switcher"],
        needs_screenshot_check=True,
        evidence_refs=["analysis:summary-navigation"],
    )

    def fake_capture(
        config: BrowserToolConfig,
        _: EvidenceBundle,
        request: BrowserScreenshotRequest,
    ) -> dict[str, Any]:
        path = config.screenshot_dir / f"{request.scenario}.png"
        path.write_bytes(b"not-a-real-png-but-not-blank")
        return {
            "scenario": request.scenario,
            "url": f"http://127.0.0.1:5173{request.url}",
            "path": str(path),
            "viewport": {"width": request.width, "height": request.height},
            "visible_text": " ".join(request.expected_text),
            "blank": False,
            "policy_audit": {
                "registry_id": "guidesync-read-only-agent-tools:v1",
                "permission": "read_only_allowed",
                "risk": "low",
                "resource_scope": "browser_read",
                "decision": "allowed",
                "timeout_ms": 15000,
                "output_limit_chars": 16000,
                "retry_policy": "At most two persisted attempts per scenario.",
            },
        }

    evidence = EvidenceBundle()
    result = capture_task_screenshots(
        screenshot_context(
            GuideSyncRunRequest(
                goal="Explain navigation updates.",
                screenshot_policy=ScreenshotPolicy.OPTIONAL,
                task_interface_url="http://127.0.0.1:5173/#/projects",
            ),
            tmp_path,
            evidence=evidence,
            file_summaries=[summary],
        ),
        capture_func=fake_capture,
    )

    plan = json.loads(Path(result.artifacts["screenshot-plan.json"]).read_text())
    assert len(plan["items"]) == 2
    assert len({item["id"] for item in plan["items"]}) == 2
    assert len({item["change_id"] for item in plan["items"]}) == 1
    assert all(item["capture_target"] == "viewport" for item in plan["items"])
    assert all(item["caption"].startswith("Where to find it:") for item in plan["items"])
    assert len(evidence.browser_screenshots) == 2
    assert all(item.publication_approved for item in evidence.browser_screenshots)
    assert all(
        item.prepared_artifact_name in result.artifacts
        for item in evidence.browser_screenshots
    )


def test_mobile_menu_change_plans_closed_and_open_mobile_states() -> None:
    request = GuideSyncRunRequest(
        goal="Покажите изменение мобильного меню.",
        screenshot_policy=ScreenshotPolicy.REQUIRED,
        task_interface_url="https://starlight.astro.build/ru/getting-started/",
    )
    request.report.locale = ReportLocale.RUSSIAN
    summary = FileChangeSummary(
        id="summary-mobile-menu",
        repository_id="starlight",
        path="packages/starlight/components/MobileMenuToggle.astro",
        status="M",
        technical_summary="The toggle swaps its open and close icons.",
        product_impact="The mobile menu now shows a close icon while open.",
        affected_components=["MobileMenuToggle"],
        needs_screenshot_check=True,
    )

    plan = build_screenshot_plan(request, [summary])

    assert [item.requested_state for item in plan.items] == [
        "mobile menu closed",
        "mobile menu open",
    ]
    assert all(item.viewport.width == 390 for item in plan.items)
    assert all(item.viewport.height == 844 for item in plan.items)
    assert plan.items[0].expected_text == []
    assert [action.kind.value for action in plan.items[1].actions] == [
        "wait_for",
        "click",
        "wait",
    ]
    assert plan.items[1].expected_text == []


def test_privacy_data_rejects_publication_image(tmp_path: Path) -> None:
    summary = FileChangeSummary(
        repository_id="repo-1",
        path="frontend/account.tsx",
        status="modified",
        technical_summary="Changed account banner.",
        product_impact="Account controls are easier to find.",
        affected_workflows=["Account controls"],
        needs_screenshot_check=True,
    )

    def fake_capture(
        config: BrowserToolConfig,
        _: EvidenceBundle,
        request: BrowserScreenshotRequest,
    ) -> dict[str, Any]:
        path = config.screenshot_dir / "account.png"
        path.write_bytes(b"not-blank")
        return {
            "scenario": request.scenario,
            "url": request.url,
            "path": str(path),
            "visible_text": "Account controls for user@example.com",
            "blank": False,
        }

    evidence = EvidenceBundle()
    result = capture_task_screenshots(
        screenshot_context(
            GuideSyncRunRequest(
                goal="Explain account controls.",
                screenshot_policy=ScreenshotPolicy.OPTIONAL,
                task_interface_url="http://127.0.0.1:5173/#/account",
            ),
            tmp_path,
            evidence=evidence,
            file_summaries=[summary],
        ),
        capture_func=fake_capture,
    )

    capture = result.captures[-1]
    assert isinstance(capture, ScreenshotCaptureResult)
    assert "privacy_sensitive_content" in capture.validation_reasons
    assert capture.publication_approved is False
    assert capture.prepared_artifact_name is None


def test_browser_rejects_cross_origin_navigation(tmp_path: Path) -> None:
    result = capture_browser_screenshot(
        BrowserToolConfig(
            enabled=True,
            base_url="http://127.0.0.1:5173/",
            screenshot_dir=tmp_path,
        ),
        EvidenceBundle(),
        BrowserScreenshotRequest(
            scenario="cross-origin",
            url="https://attacker.example/",
        ),
    )

    assert result["error"]["code"] == "browser_origin_denied"


def test_browser_steps_require_semantic_locators() -> None:
    assert parse_browser_step("click role=button name=Save") == {
        "action": "click",
        "locator_kind": "role",
        "locator": "button",
        "role_name": "Save",
    }
    with pytest.raises(ValueError, match="semantic syntax"):
        parse_browser_step("click #save")


def test_main_capture_clip_excludes_layout_padding_and_stays_in_viewport() -> None:
    assert bounded_content_clip(
        {"x": 0.0, "y": 0.0, "width": 1440.0, "height": 1100.0},
        {"left": "324px", "right": "20px", "top": "20px", "bottom": "20px"},
        {"width": 1440, "height": 1000},
    ) == {
        "x": 324.0,
        "y": 20.0,
        "width": 1096.0,
        "height": 980.0,
    }


def test_prepared_capture_masks_stable_internal_identifiers() -> None:
    assert privacy_mask_values(
        "Profile profile-74ec88fc44 belongs to run-1234abcd and ordinary-project-name."
    ) == ["profile-74ec88fc44", "run-1234abcd"]


def test_prepared_capture_masks_every_matching_identifier_occurrence() -> None:
    class FakeLocator:
        def __init__(self, text: str = "") -> None:
            self.text = text

        def inner_text(self, timeout: int) -> str:
            assert timeout == 1_000
            return self.text

        def count(self) -> int:
            return 2

        @property
        def first(self) -> None:
            raise AssertionError("mask locators must retain every matching element")

    matching_locator = FakeLocator()

    class FakePage:
        def locator(self, selector: str) -> FakeLocator:
            assert selector == "body"
            return FakeLocator("profile-74ec88fc44 appears twice: profile-74ec88fc44")

        def get_by_text(self, value: str, *, exact: bool) -> FakeLocator:
            assert value == "profile-74ec88fc44"
            assert exact is True
            return matching_locator

    locators, records = privacy_mask_targets(FakePage())

    assert locators == [matching_locator]
    assert [record.locator for record in records] == ["profile-74ec88fc44"]


def test_model_browser_steps_are_preserved_as_typed_plan_actions() -> None:
    actions = screenshot_actions_for_steps(
        [
            "goto /#/projects",
            "click role=button name=Projects",
            "wait_for testid=project-list",
            "wait 9000",
        ]
    )

    assert [action.kind for action in actions] == [
        ScreenshotActionKind.NAVIGATE,
        ScreenshotActionKind.CLICK,
        ScreenshotActionKind.WAIT_FOR,
        ScreenshotActionKind.WAIT,
    ]
    assert actions[1].locator_kind is ScreenshotLocatorKind.ROLE
    assert actions[1].role_name == "Projects"
    assert actions[2].locator_kind is ScreenshotLocatorKind.TEST_ID
    assert actions[3].wait_ms == 5_000


def test_typed_plan_actions_compile_to_bounded_browser_steps() -> None:
    item = ScreenshotPlanItem(
        id="scenario-1",
        change_id="change-1",
        claim_id="claim-1",
        claim="Project controls are visible.",
        route="/#/projects",
        actions=[
            ScreenshotAction(
                kind=ScreenshotActionKind.CLICK,
                locator_kind=ScreenshotLocatorKind.ROLE,
                locator="button",
                role_name="Projects",
            ),
            ScreenshotAction(
                kind=ScreenshotActionKind.WAIT_FOR,
                locator_kind=ScreenshotLocatorKind.TEST_ID,
                locator="project-list",
            ),
            ScreenshotAction(kind=ScreenshotActionKind.WAIT, wait_ms=250),
        ],
        requested_state="Project controls are visible.",
        caption="Project controls",
        alt_text="Updated project controls",
    )

    assert browser_steps_for_plan_item(item) == [
        "click role=button name=Projects",
        "wait_for testid=project-list",
        "wait 250",
    ]
    with pytest.raises(ValueError, match="require locator_kind"):
        ScreenshotAction(kind=ScreenshotActionKind.CLICK)


def test_browser_interaction_rejects_redirected_origin() -> None:
    with pytest.raises(ValueError, match="left the configured"):
        ensure_allowed_page_origin(
            SimpleNamespace(url="https://attacker.example/"),
            "http://127.0.0.1:5173",
        )
