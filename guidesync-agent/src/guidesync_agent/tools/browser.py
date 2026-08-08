from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from importlib import import_module
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext

from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    EvidenceBundle,
    OperationError,
    ProviderConfig,
)
from guidesync_agent.settings import BrowserToolSettings, get_settings
from guidesync_agent.tools.browser_models import (
    BrowserCaptureContext,
    BrowserCaptureDiagnostics,
    BrowserCaptureErrorCode,
    BrowserCaptureFailure,
    BrowserScreenshotRequest,
)

try:
    playwright_sync_api = import_module("playwright.sync_api")
except ImportError:
    sync_playwright = None
else:
    sync_playwright = playwright_sync_api.sync_playwright


DEFAULT_SCREENSHOT_WIDTH = 1440
DEFAULT_SCREENSHOT_HEIGHT = 1000


BrowserToolConfig = BrowserToolSettings


def browser_tool_config_from_provider(config: ProviderConfig) -> BrowserToolConfig:
    return config.browser or get_settings().browser.tool_settings()


def register_browser_agent_tools(agent: Any) -> None:
    @agent.tool
    def capture_ui_screenshot(  # noqa: PLR0913 - model-facing tool schema
        ctx: RunContext[Any],
        scenario: str,
        url: str | None = None,
        steps: list[str] | None = None,
        width: int = DEFAULT_SCREENSHOT_WIDTH,
        height: int = DEFAULT_SCREENSHOT_HEIGHT,
    ) -> dict[str, Any]:
        """Capture a UI screenshot for a named user scenario.

        Steps are plain strings: `click <selector>`, `fill <selector> = <value>`,
        `wait_for_selector <selector>`, `wait <milliseconds>`, or `goto <url>`.
        """
        ctx.deps.tool_calls += 1
        result = capture_browser_screenshot(
            ctx.deps.browser,
            ctx.deps.evidence,
            BrowserScreenshotRequest(
                scenario=scenario,
                url=url,
                steps=steps or [],
                width=width,
                height=height,
            ),
        )
        return result


def capture_browser_screenshot(
    config: BrowserToolConfig,
    evidence: EvidenceBundle,
    request: BrowserScreenshotRequest,
) -> dict[str, Any]:
    if not config.enabled:
        return dump_browser_capture(
            browser_capture_failure(
                BrowserCaptureErrorCode.DISABLED,
                "Browser screenshot tool is disabled.",
            )
        )

    target_url = request.url or config.base_url
    if not target_url:
        return dump_browser_capture(
            browser_capture_failure(
                BrowserCaptureErrorCode.URL_REQUIRED,
                "Browser URL is required. Pass url or configure browser.base_url.",
            )
        )

    config.screenshot_dir.mkdir(parents=True, exist_ok=True)
    context = BrowserCaptureContext(
        evidence=evidence,
        scenario=request.scenario,
        target_url=target_url,
        path=screenshot_path(config.screenshot_dir, request.scenario),
        steps=request.steps,
        width=request.width,
        height=request.height,
        timeout_ms=config.timeout_ms,
        expected_text=request.expected_text,
        browser_binary=config.binary,
    )
    if sync_playwright is not None:
        return dump_browser_capture(capture_with_playwright(context))

    if request.steps:
        return dump_browser_capture(
            browser_capture_failure(
                BrowserCaptureErrorCode.PLAYWRIGHT_UNAVAILABLE,
                (
                    "Playwright is not installed, so scenario steps cannot be executed. "
                    "Install Playwright or call this tool with no interaction steps."
                ),
            )
        )
    return dump_browser_capture(capture_with_chrome_cli(context))


def capture_with_playwright(
    context: BrowserCaptureContext,
) -> BrowserScreenshotEvidence | BrowserCaptureFailure:
    playwright_runner = sync_playwright
    if playwright_runner is None:
        return browser_capture_failure(
            BrowserCaptureErrorCode.PLAYWRIGHT_UNAVAILABLE,
            "Playwright is not installed.",
        )
    try:
        with playwright_runner() as playwright:
            console_errors: list[str] = []
            network_errors: list[str] = []
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": context.width, "height": context.height}
            )
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )
            page.on(
                "requestfailed",
                lambda request: network_errors.append(request.url),
            )
            page.goto(
                context.target_url,
                wait_until="networkidle",
                timeout=context.timeout_ms,
            )
            for step in context.steps:
                execute_browser_step(page, parse_browser_step(step), context.timeout_ms)
            title = page.title()
            visible_text = page.locator("body").inner_text(timeout=1000)
            page.screenshot(path=str(context.path), full_page=True)
            browser.close()
    except Exception as exc:  # noqa: BLE001 - return tool error to the agent
        return browser_capture_failure(
            BrowserCaptureErrorCode.CAPTURE_FAILED,
            f"Browser screenshot failed: {exc}",
            retryable=True,
        )
    return record_screenshot(
        context,
        BrowserCaptureDiagnostics(
            notes="Captured with Playwright.",
            title=title,
            visible_text=visible_text,
            console_errors=console_errors,
            network_errors=network_errors,
        ),
    )


def capture_with_chrome_cli(
    context: BrowserCaptureContext,
) -> BrowserScreenshotEvidence | BrowserCaptureFailure:
    browser = find_browser_binary(context.browser_binary)
    if browser is None:
        return browser_capture_failure(
            BrowserCaptureErrorCode.BROWSER_UNAVAILABLE,
            "No browser binary was found and Playwright is not installed.",
        )
    completed = subprocess.run(
        [
            browser,
            "--headless=new",
            "--disable-gpu",
            f"--screenshot={context.path}",
            f"--window-size={context.width},{context.height}",
            f"--timeout={context.timeout_ms}",
            context.target_url,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=max(5, int(context.timeout_ms / 1000) + 5),
    )
    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip() or "Browser exited non-zero."
        return browser_capture_failure(
            BrowserCaptureErrorCode.PROCESS_FAILED,
            error,
            retryable=True,
        )
    return record_screenshot(
        context,
        BrowserCaptureDiagnostics(notes="Captured with browser CLI."),
    )


def parse_browser_step(step: str) -> dict[str, str]:
    stripped = step.strip()
    action, _, rest = stripped.partition(" ")
    action = action.strip().lower()
    rest = rest.strip()
    if action == "goto":
        return {"action": action, "value": rest}
    if action in {"click", "wait_for_selector"}:
        return {"action": action, "selector": rest}
    if action == "fill":
        selector, separator, value = rest.partition("=")
        if not separator:
            raise ValueError("fill step must use: fill <selector> = <value>")
        return {
            "action": action,
            "selector": selector.strip(),
            "value": value.strip(),
        }
    if action == "wait":
        return {"action": action, "value": rest}
    raise ValueError(f"Unsupported browser step: {step}")


def execute_browser_step(page: Any, step: dict[str, str], timeout_ms: int) -> None:
    action = step.get("action", "").strip().lower()
    selector = step.get("selector")
    value = step.get("value", "")
    if action == "goto":
        page.goto(value, wait_until="networkidle", timeout=timeout_ms)
        return
    if action == "click" and selector:
        page.click(selector, timeout=timeout_ms)
        return
    if action == "fill" and selector:
        page.fill(selector, value, timeout=timeout_ms)
        return
    if action == "wait_for_selector" and selector:
        page.wait_for_selector(selector, timeout=timeout_ms)
        return
    if action == "wait":
        page.wait_for_timeout(int(value or "1000"))
        return
    raise ValueError(f"Unsupported browser step: {step}")


def record_screenshot(
    context: BrowserCaptureContext,
    diagnostics: BrowserCaptureDiagnostics,
) -> BrowserScreenshotEvidence:
    image_hash = file_hash(context.path)
    blank = is_blank_screenshot(context.path)
    matched_text = [
        item
        for item in context.expected_text
        if item.lower() in diagnostics.visible_text.lower()
    ]
    missing_text = [item for item in context.expected_text if item not in matched_text]
    screenshot = BrowserScreenshotEvidence(
        scenario=context.scenario,
        url=context.target_url,
        path=str(context.path),
        title=diagnostics.title,
        viewport=context.viewport,
        visible_text=diagnostics.visible_text,
        matched_text=matched_text,
        missing_text=missing_text,
        console_errors=diagnostics.console_errors,
        network_errors=diagnostics.network_errors,
        image_hash=image_hash,
        blank=blank,
        notes=diagnostics.notes,
    )
    context.evidence.browser_screenshots.append(screenshot)
    return screenshot


def browser_capture_failure(
    code: BrowserCaptureErrorCode,
    message: str,
    *,
    retryable: bool = False,
) -> BrowserCaptureFailure:
    return BrowserCaptureFailure(
        error=OperationError(
            code=code.value,
            message=message,
            retryable=retryable,
        )
    )


def dump_browser_capture(
    capture: BrowserScreenshotEvidence | BrowserCaptureFailure,
) -> dict[str, Any]:
    return capture.model_dump(mode="json")


def file_hash(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def is_blank_screenshot(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return True
    if not data:
        return True
    return len(set(data[:4096])) <= 2 and len(data) < 4096


def screenshot_path(directory: Path, scenario: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", scenario.strip().lower()).strip("-")
    name = safe or "ui-screenshot"
    path = directory / f"{name}.png"
    counter = 2
    while path.exists():
        path = directory / f"{name}-{counter}.png"
        counter += 1
    return path


def find_browser_binary(configured_binary: Path | None = None) -> str | None:
    configured_binary = configured_binary or get_settings().browser.binary
    candidates = [
        str(configured_binary) if configured_binary else None,
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
        shutil.which("chrome"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None
