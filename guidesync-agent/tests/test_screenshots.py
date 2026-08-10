from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from guidesync_agent.schemas import (
    AnalysisArtifactManifest,
    BrowserScreenshotEvidence,
    EvidenceBundle,
    ReportLocale,
    ScreenshotActionKind,
    ScreenshotLocatorKind,
    ScreenshotValidationStatus,
)
from guidesync_agent.services.screenshot_validation import wrong_language
from guidesync_agent.services.screenshots import screenshot_evidence_artifacts
from guidesync_agent.tools.browser import (
    BrowserToolConfig,
    capture_browser_screenshot,
    inspect_browser_ui,
    register_browser_agent_tools,
)
from guidesync_agent.tools.browser_evidence import dump_browser_capture, record_screenshot
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
from guidesync_agent.tools.evidence import EvidenceAgentDeps


def test_browser_tool_imports_in_fresh_interpreter() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from guidesync_agent.tools.browser import inspect_browser_ui",
        ],
        check=True,
        timeout=10,
    )


def test_browser_agent_rejects_unchanged_failed_screenshot_retry(monkeypatch) -> None:
    registered: dict[str, Any] = {}
    capture_calls = 0
    capture_scenarios: list[str] = []
    capture_expected_text: list[list[str]] = []

    class FakeAgent:
        def tool(self, function):
            registered[function.__name__] = function
            return function

    def fail_capture(_config, _evidence, request) -> dict[str, Any]:
        nonlocal capture_calls
        capture_calls += 1
        capture_scenarios.append(request.scenario)
        capture_expected_text.append(request.expected_text)
        return {
            "error": {
                "code": "browser_capture_failed",
                "message": "Wrong state.",
                "retryable": True,
            }
        }

    monkeypatch.setattr(
        "guidesync_agent.tools.browser.capture_browser_screenshot",
        fail_capture,
    )
    register_browser_agent_tools(FakeAgent())
    capture = registered["capture_ui_screenshot"]
    context = SimpleNamespace(
        deps=EvidenceAgentDeps(
            evidence=EvidenceBundle(),
            browser=BrowserToolConfig(base_url="https://example.com/product"),
        )
    )
    arguments = {
        "change_id": "change-navigation",
        "claim": "Navigation changes in a responsive layout.",
        "route": "/product",
        "expected_text": ["Menu"],
        "rejected_text": [f"failure-{index}" for index in range(8)] + ["ignored-a"],
        "caption": "Responsive navigation",
        "alt_text": "Responsive navigation controls.",
        "evidence_refs": ["analysis:change-navigation"],
        "actions": ["click role=button name=Menu"],
    }

    first = capture(context, **arguments)
    duplicate = capture(
        context,
        **{
            **arguments,
            "route": "https://example.com/product",
            "rejected_text": [f"failure-{index}" for index in range(8)] + ["ignored-b"],
            "actions": ["  click role=button name=Menu  "],
        },
    )
    varied = capture(context, **{**arguments, "width": 390, "height": 844})

    assert first["error"]["code"] == "browser_capture_failed"
    assert duplicate["error"]["code"] == "browser_invalid_action"
    assert "Duplicate screenshot attempt" in duplicate["error"]["message"]
    assert varied["error"]["code"] == "browser_capture_failed"
    assert capture_calls == 2
    assert len(set(capture_scenarios)) == 2
    assert capture_expected_text == [[], []]


def test_invalid_screenshot_plan_does_not_consume_retry_signature(monkeypatch) -> None:
    registered: dict[str, Any] = {}
    capture_calls = 0

    class FakeAgent:
        def tool(self, function):
            registered[function.__name__] = function
            return function

    def fail_capture(_config, _evidence, _request) -> dict[str, Any]:
        nonlocal capture_calls
        capture_calls += 1
        return {
            "error": {
                "code": "browser_capture_failed",
                "message": "Wrong state.",
                "retryable": True,
            }
        }

    monkeypatch.setattr(
        "guidesync_agent.tools.browser.capture_browser_screenshot",
        fail_capture,
    )
    register_browser_agent_tools(FakeAgent())
    capture = registered["capture_ui_screenshot"]
    context = SimpleNamespace(
        deps=EvidenceAgentDeps(
            evidence=EvidenceBundle(),
            browser=BrowserToolConfig(base_url="https://example.com/product"),
        )
    )
    arguments = {
        "change_id": "change-navigation",
        "claim": "Navigation changes in a responsive layout.",
        "route": "/product",
        "expected_text": [],
        "rejected_text": [],
        "caption": "Responsive navigation",
        "alt_text": "Responsive navigation controls.",
        "evidence_refs": ["analysis:change-navigation"],
        "actions": ["click role=button name=Menu"],
    }

    invalid = capture(context, **arguments, theme="sepia")
    valid = capture(context, **arguments, theme="light")

    assert invalid["error"]["code"] == "browser_invalid_action"
    assert "Invalid screenshot plan" in invalid["error"]["message"]
    assert valid["error"]["code"] == "browser_capture_failed"
    assert capture_calls == 1


def test_browser_agent_rejects_screenshot_for_unknown_change_id(monkeypatch) -> None:
    registered: dict[str, Any] = {}

    class FakeAgent:
        def tool(self, function):
            registered[function.__name__] = function
            return function

    monkeypatch.setattr(
        "guidesync_agent.tools.browser.capture_browser_screenshot",
        lambda *_args: pytest.fail("capture must not run for an unknown change id"),
    )
    register_browser_agent_tools(FakeAgent())
    context = SimpleNamespace(
        deps=EvidenceAgentDeps(
            evidence=EvidenceBundle(),
            browser=BrowserToolConfig(base_url="https://example.com/product"),
            analysis_manifest=AnalysisArtifactManifest(
                run_id="run-1",
                plan_task_id="plan-1",
                artifacts=[],
            ),
        )
    )

    result = registered["capture_ui_screenshot"](
        context,
        change_id="invented-change",
        claim="A claimed UI change.",
        route="/product",
        expected_text=[],
        rejected_text=[],
        caption="Changed interface",
        alt_text="Changed interface.",
        evidence_refs=[],
    )

    assert result["error"]["code"] == "browser_invalid_action"
    assert "exact id from the analysis manifest" in result["error"]["message"]


def test_browser_inspection_rejects_cross_origin_route(tmp_path: Path) -> None:
    result = inspect_browser_ui(
        BrowserToolConfig(
            enabled=True,
            base_url="https://example.com/product",
            screenshot_dir=tmp_path,
        ),
        "https://attacker.example/",
        width=390,
        height=844,
    )

    assert result["error"]["code"] == "browser_origin_denied"
    assert result["policy_audit"]["resource_scope"] == "browser_read"


def test_browser_agent_rejects_duplicate_ui_inspection(monkeypatch) -> None:
    registered: dict[str, Any] = {}
    inspection_calls = 0

    class FakeAgent:
        def tool(self, function):
            registered[function.__name__] = function
            return function

    def inspect(_config, route, *, width, height) -> dict[str, Any]:
        nonlocal inspection_calls
        inspection_calls += 1
        return {"url": route, "viewport": {"width": width, "height": height}}

    monkeypatch.setattr("guidesync_agent.tools.browser.inspect_browser_ui", inspect)
    register_browser_agent_tools(FakeAgent())
    context = SimpleNamespace(
        deps=EvidenceAgentDeps(
            evidence=EvidenceBundle(),
            browser=BrowserToolConfig(base_url="https://example.com/product"),
        )
    )

    first = registered["inspect_ui"](context, "/product", width=375)
    duplicate = registered["inspect_ui"](
        context,
        "https://example.com/product",
        width=375,
    )
    varied = registered["inspect_ui"](context, "/product", width=390)

    assert first["viewport"]["width"] == 375
    assert duplicate["error"]["code"] == "browser_invalid_action"
    assert "Duplicate UI inspection" in duplicate["error"]["message"]
    assert duplicate["policy_audit"]["retry_policy"] == "no automatic retry"
    assert varied["viewport"]["width"] == 390
    assert inspection_calls == 2


def test_browser_agent_retries_same_inspection_after_transient_failure(monkeypatch) -> None:
    registered: dict[str, Any] = {}
    inspection_calls = 0

    class FakeAgent:
        def tool(self, function):
            registered[function.__name__] = function
            return function

    def inspect(_config, route, *, width, height) -> dict[str, Any]:
        nonlocal inspection_calls
        inspection_calls += 1
        if inspection_calls == 1:
            return {"error": {"code": "browser_capture_failed", "retryable": True}}
        return {"url": route, "viewport": {"width": width, "height": height}}

    monkeypatch.setattr("guidesync_agent.tools.browser.inspect_browser_ui", inspect)
    register_browser_agent_tools(FakeAgent())
    context = SimpleNamespace(
        deps=EvidenceAgentDeps(
            evidence=EvidenceBundle(),
            browser=BrowserToolConfig(base_url="https://example.com/product"),
        )
    )

    failed = registered["inspect_ui"](context, "/product", width=375)
    recovered = registered["inspect_ui"](context, "/product", width=375)
    duplicate = registered["inspect_ui"](context, "/product", width=375)

    assert failed["error"]["code"] == "browser_capture_failed"
    assert recovered["viewport"]["width"] == 375
    assert "Duplicate UI inspection" in duplicate["error"]["message"]
    assert inspection_calls == 2


def test_english_screenshot_rejects_material_cyrillic_text() -> None:
    assert wrong_language("abcdefghijklmnopqrяя", ReportLocale.ENGLISH)
    assert not wrong_language("abcdefghijklmnopqrsя", ReportLocale.ENGLISH)


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


def test_screenshot_evidence_artifacts_publish_only_approved_prepared_images(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw.png"
    prepared = tmp_path / "prepared.png"
    rejected = tmp_path / "rejected.png"
    evidence = EvidenceBundle(
        browser_screenshots=[
            BrowserScreenshotEvidence(
                scenario="approved",
                url="https://example.com/product",
                path=str(prepared),
                raw_path=str(raw),
                prepared_artifact_name="prepared.png",
                publication_approved=True,
                validation_status=ScreenshotValidationStatus.PASSED,
            ),
            BrowserScreenshotEvidence(
                scenario="rejected",
                url="https://example.com/product",
                path=str(rejected),
                publication_approved=False,
                validation_status=ScreenshotValidationStatus.FAILED,
            ),
        ]
    )

    artifacts = screenshot_evidence_artifacts(tmp_path / "report", evidence)

    assert artifacts["raw.png"] == str(raw)
    assert artifacts["prepared.png"] == str(prepared)
    assert "rejected.png" not in artifacts
    manifest = json.loads(Path(artifacts["screenshot-evidence.json"]).read_text())
    assert [item["scenario"] for item in manifest["screenshots"]] == [
        "approved",
        "rejected",
    ]


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


def test_browser_interaction_rejects_redirected_origin() -> None:
    with pytest.raises(ValueError, match="left the configured"):
        ensure_allowed_page_origin(
            SimpleNamespace(url="https://attacker.example/"),
            "http://127.0.0.1:5173",
        )
