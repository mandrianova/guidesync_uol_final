from __future__ import annotations

import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import SecretStr

from guidesync_agent.schemas import (
    AnalysisArtifactManifest,
    BrowserScreenshotEvidence,
    EvidenceBundle,
    ReportLocale,
    ScreenshotActionKind,
    ScreenshotCaptureResult,
    ScreenshotLocatorKind,
    ScreenshotPlanItem,
    ScreenshotRetryDisposition,
    ScreenshotValidationAttempt,
    ScreenshotValidationStatus,
    TaskInterfaceAuthType,
)
from guidesync_agent.services.ui_evidence.screenshots import screenshot_evidence_artifacts
from guidesync_agent.services.ui_evidence.validation import page_state_reasons, wrong_language
from guidesync_agent.tools.browser import (
    BrowserToolConfig,
    capture_browser_screenshot,
    inspect_browser_ui,
    prepare_agent_screenshot,
    register_browser_agent_tools,
    screenshot_capture_tool_result,
    task_interface_cookie_entries,
)
from guidesync_agent.tools.browser_evidence import dump_browser_capture, record_screenshot
from guidesync_agent.tools.browser_models import (
    BrowserCaptureContext,
    BrowserCaptureDiagnostics,
    BrowserScreenshotRequest,
)
from guidesync_agent.tools.browser_support import (
    bounded_content_clip,
    capture_prepared_image,
    ensure_allowed_page_origin,
    execute_browser_step,
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


def test_auth_cookie_is_parsed_and_scoped_to_effective_ui_origin() -> None:
    entries = task_interface_cookie_entries(
        SecretStr("session=secret-value; theme=dark"),
        "https://product.example.com/private/page?tab=one",
    )

    assert entries == [
        {
            "name": "session",
            "value": "secret-value",
            "url": "https://product.example.com",
        },
        {
            "name": "theme",
            "value": "dark",
            "url": "https://product.example.com",
        },
    ]


def test_browser_cookie_opens_a_protected_same_origin_page(tmp_path: Path) -> None:
    class ProtectedPageHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            authorized = self.headers.get("Cookie") == "session=authorized"
            body = b"<main>Private dashboard</main>" if authorized else b"<main>Sign in</main>"
            self.send_response(200 if authorized else 401)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), ProtectedPageHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        result = inspect_browser_ui(
            BrowserToolConfig(
                base_url=base_url,
                screenshot_dir=tmp_path,
                auth_type=TaskInterfaceAuthType.COOKIE,
                auth_secret=SecretStr("session=authorized"),
            ),
            "/",
            width=800,
            height=600,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    error = result.get("error")
    if isinstance(error, dict) and "Executable doesn't exist" in str(error.get("message", "")):
        pytest.skip("Playwright Chromium is not installed in the host test environment.")

    assert "visible_text" in result, result
    assert result["visible_text"] == "Private dashboard"
    assert "authorized" not in json.dumps(result)


def test_browser_local_storage_is_injected_before_first_navigation(tmp_path: Path) -> None:
    class ProtectedPageHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"""
                <main id="app"></main>
                <script>
                  const token = window.localStorage.getItem("accessToken");
                  document.querySelector("#app").textContent =
                    token === "authorized" ? "Private dashboard" : "Sign in";
                </script>
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), ProtectedPageHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        result = inspect_browser_ui(
            BrowserToolConfig(
                base_url=base_url,
                screenshot_dir=tmp_path,
                auth_type=TaskInterfaceAuthType.LOCAL_STORAGE,
                auth_secret=SecretStr('{"accessToken":"authorized"}'),
            ),
            "/",
            width=800,
            height=600,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    error = result.get("error")
    if isinstance(error, dict) and "Executable doesn't exist" in str(error.get("message", "")):
        pytest.skip("Playwright Chromium is not installed in the host test environment.")

    assert result["visible_text"] == "Private dashboard"
    assert "authorized" not in json.dumps(result)


def test_browser_agent_rejects_duplicate_ui_inspection(monkeypatch) -> None:
    registered: dict[str, Any] = {}
    inspection_calls = 0

    class FakeAgent:
        def tool(self, function):
            registered[function.__name__] = function
            return function

    def inspect(_config, route, *, actions, width, height) -> dict[str, Any]:
        nonlocal inspection_calls
        inspection_calls += 1
        return {
            "url": route,
            "actions": actions,
            "viewport": {"width": width, "height": height},
        }

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
    action_inspection = registered["inspect_ui"](
        context,
        "/product",
        actions=["click text=Settings"],
        width=375,
    )

    assert first["viewport"]["width"] == 375
    assert duplicate["error"]["code"] == "browser_invalid_action"
    assert "Duplicate UI inspection" in duplicate["error"]["message"]
    assert duplicate["policy_audit"]["retry_policy"] == "no automatic retry"
    assert varied["viewport"]["width"] == 390
    assert action_inspection["actions"] == [
        {"action": "click", "locator_kind": "text", "locator": "Settings"}
    ]
    assert inspection_calls == 3


def test_browser_agent_retries_same_inspection_after_transient_failure(monkeypatch) -> None:
    registered: dict[str, Any] = {}
    inspection_calls = 0

    class FakeAgent:
        def tool(self, function):
            registered[function.__name__] = function
            return function

    def inspect(_config, route, *, actions, width, height) -> dict[str, Any]:
        nonlocal inspection_calls
        del actions
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


def test_goto_uses_dom_content_loaded_without_waiting_for_network_idle() -> None:
    class Page:
        url = "https://example.com/settings"

        def __init__(self) -> None:
            self.goto_options: dict[str, Any] = {}
            self.waited_ms = 0

        def goto(self, target: str, **options: Any) -> None:
            self.url = target
            self.goto_options = options

        def wait_for_timeout(self, milliseconds: int) -> None:
            self.waited_ms = milliseconds

    page = Page()

    execute_browser_step(
        page,
        {"action": "goto", "value": "/settings"},
        15_000,
        allowed_origin="https://example.com",
    )

    assert page.goto_options == {"wait_until": "domcontentloaded", "timeout": 15_000}
    assert page.waited_ms == 1_000


def test_browser_step_accepts_quoted_accessible_name() -> None:
    assert parse_browser_step(
        'click role=button name="MA Margarita Andrianova · Free"'
    ) == {
        "action": "click",
        "locator_kind": "role",
        "locator": "button",
        "role_name": "MA Margarita Andrianova · Free",
    }


def test_screenshot_language_uses_dominant_script() -> None:
    cyrillic_dominant = (
        "abcdefgh\u0430\u0431\u0432\u0433\u0434\u0435\u0436\u0437\u0438\u0439\u043a\u043b"
    )
    latin_dominant = "abcdefghijklmnopqr\u044f\u044f"

    assert wrong_language(cyrillic_dominant, ReportLocale.ENGLISH)
    assert not wrong_language(latin_dominant, ReportLocale.ENGLISH)
    assert not wrong_language(cyrillic_dominant, ReportLocale.RUSSIAN)
    assert wrong_language(latin_dominant, ReportLocale.RUSSIAN)


def test_documentation_password_example_is_not_an_auth_page() -> None:
    reasons = page_state_reasons(
        "Danger: Do not give your password to anyone.",
        "Asides | Starlight",
        ReportLocale.ENGLISH,
    )

    assert "auth_page" not in reasons


def test_sign_in_page_is_auth_page() -> None:
    reasons = page_state_reasons(
        "Email Password Forgot password? Sign in",
        "Account",
        ReportLocale.ENGLISH,
    )

    assert "auth_page" in reasons


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
            attempt=2,
            retry_of_capture_id="capture-first",
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
    assert screenshot.attempt == 2
    assert screenshot.retry_of_capture_id == "capture-first"


def test_capture_tool_result_keeps_actionable_review_without_audit_blob(
    tmp_path: Path,
) -> None:
    capture = ScreenshotCaptureResult(
        scenario="billing",
        scenario_id="scenario-billing",
        capture_id="capture-billing",
        change_id="billing-change",
        url="https://example.com/app/",
        path=str(tmp_path / "billing.png"),
        requested_state="The Plans tab is visible.",
        observed_state="Billing exposes Manage plans but no Plans tab.",
        validation_status=ScreenshotValidationStatus.FAILED,
        dom_snapshot="x" * 40_000,
        visible_text="y" * 20_000,
    )
    validation = ScreenshotValidationAttempt(
        status=ScreenshotValidationStatus.FAILED,
        reasons=["semantic_mismatch"],
        retry_disposition=ScreenshotRetryDisposition.UNAVAILABLE,
        semantic_mismatches=["The requested Plans tab does not exist."],
    )

    result = screenshot_capture_tool_result(capture, validation)

    assert result["retry_disposition"] == "unavailable"
    assert result["retry_recommended"] is False
    assert "Do not retry" in result["next_action"]
    assert "dom_snapshot" not in result
    assert "visible_text" not in result
    assert len(json.dumps(result)) < 3_000


def test_screenshot_evidence_artifacts_publish_only_approved_prepared_images(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw.png"
    prepared = tmp_path / "prepared.png"
    rejected = tmp_path / "rejected.png"
    raw.write_bytes(b"raw")
    prepared.write_bytes(b"prepared")
    rejected.write_bytes(b"rejected")
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


def test_screenshot_evidence_artifacts_skip_stale_local_capture_paths(
    tmp_path: Path,
) -> None:
    evidence = EvidenceBundle(
        browser_screenshots=[
            BrowserScreenshotEvidence(
                scenario="stale",
                url="https://example.com/product",
                path=str(tmp_path / "missing-prepared.png"),
                raw_path=str(tmp_path / "missing-raw.png"),
                prepared_artifact_name="missing-prepared.png",
                publication_approved=True,
                validation_status=ScreenshotValidationStatus.PASSED,
            )
        ]
    )

    artifacts = screenshot_evidence_artifacts(tmp_path / "report", evidence)

    assert set(artifacts) == {"screenshot-evidence.json"}


def test_text_capture_target_scrolls_target_and_keeps_viewport_context(
    tmp_path: Path,
) -> None:
    target = SimpleNamespace(
        scrolled=False,
        scroll_into_view_if_needed=lambda **_kwargs: setattr(target, "scrolled", True),
    )

    class FakePage:
        def __init__(self) -> None:
            self.screenshot_options: dict[str, Any] = {}

        def locator(self, _selector: str) -> SimpleNamespace:
            return SimpleNamespace(inner_text=lambda **_kwargs: "Icons Reference forgejo")

        def get_by_text(self, value: str, *, exact: bool) -> Any:
            assert value == "forgejo"
            assert exact is True
            return target

        def screenshot(self, **kwargs: Any) -> None:
            self.screenshot_options = kwargs

    page = FakePage()
    context = BrowserCaptureContext(
        evidence=EvidenceBundle(),
        scenario="forgejo",
        target_url="https://example.com/reference/icons/",
        path=tmp_path / "forgejo.png",
        steps=[],
        width=1440,
        height=1000,
        timeout_ms=15_000,
        expected_text=["forgejo"],
        plan_item=ScreenshotPlanItem(
            id="forgejo",
            change_id="forgejo",
            claim_id="forgejo-claim",
            claim="Forgejo is visible.",
            route="/reference/icons/",
            requested_state="Forgejo is visible.",
            capture_target="text=forgejo",
            caption="Forgejo icon",
            alt_text="Forgejo icon in the icon reference",
        ),
    )

    prepared = capture_prepared_image(page, context)

    assert target.scrolled is True
    assert page.screenshot_options["full_page"] is False
    assert prepared.crop.mode == "viewport-target"
    assert prepared.crop.width == 1440
    assert prepared.crop.height == 1000


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
        "margo@example.com owns profile-74ec88fc44 in run-1234abcd; token=secret."
    ) == [
        "margo@example.com",
        "token=secret.",
        "profile-74ec88fc44",
        "run-1234abcd",
    ]


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


def test_screenshot_retry_links_to_previous_capture_for_change() -> None:
    previous = BrowserScreenshotEvidence(
        scenario="scenario-first",
        capture_id="capture-first",
        change_id="change-team",
        url="https://example.com/team",
        path="/tmp/first.png",
        attempt=1,
    )
    context = SimpleNamespace(
        deps=EvidenceAgentDeps(
            evidence=EvidenceBundle(browser_screenshots=[previous]),
            browser=BrowserToolConfig(base_url="https://example.com"),
        )
    )

    prepared = prepare_agent_screenshot(
        cast(Any, context),
        change_id="change-team",
        claim="The responsive member row is visible.",
        route="/team",
        expected_text=["Creator"],
        rejected_text=["Loading"],
        caption="Responsive member row",
        alt_text="A responsive member row.",
        evidence_refs=["analysis:change-team"],
        actions=None,
        theme="light",
        capture_target="viewport",
        width=1280,
        height=900,
    )

    assert not isinstance(prepared, dict)
    assert prepared.request.attempt == 2
    assert prepared.request.retry_of_capture_id == "capture-first"


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
