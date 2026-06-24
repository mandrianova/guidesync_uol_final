from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext

from guidesync_agent.schemas import BrowserScreenshotEvidence, EvidenceBundle, ProviderConfig

try:
    playwright_sync_api = import_module("playwright.sync_api")
except ImportError:
    sync_playwright = None
else:
    sync_playwright = playwright_sync_api.sync_playwright


DEFAULT_SCREENSHOT_WIDTH = 1440
DEFAULT_SCREENSHOT_HEIGHT = 1000


@dataclass(frozen=True)
class BrowserToolConfig:
    enabled: bool = True
    base_url: str | None = None
    screenshot_dir: Path = Path("outputs/browser-screenshots")
    timeout_ms: int = 15000


def browser_tool_config_from_provider(config: ProviderConfig) -> BrowserToolConfig:
    metadata = config.metadata
    enabled_value = metadata.get("browser_tool_enabled", True)
    enabled = (
        enabled_value if isinstance(enabled_value, bool) else str(enabled_value).lower() != "false"
    )
    base_url = str(
        metadata.get("browser_base_url") or os.environ.get("GUIDESYNC_BROWSER_BASE_URL") or ""
    )
    screenshot_dir = Path(
        str(
            metadata.get("screenshot_dir")
            or os.environ.get("GUIDESYNC_SCREENSHOT_DIR")
            or "outputs/browser-screenshots"
        )
    )
    timeout_value = (
        metadata.get("browser_timeout_ms")
        or os.environ.get("GUIDESYNC_BROWSER_TIMEOUT_MS")
        or "15000"
    )
    timeout_ms = int(timeout_value)
    return BrowserToolConfig(
        enabled=enabled,
        base_url=base_url or None,
        screenshot_dir=screenshot_dir,
        timeout_ms=timeout_ms,
    )


def register_browser_agent_tools(agent: Any) -> None:
    @agent.tool
    def capture_ui_screenshot(
        ctx: RunContext[Any],
        scenario: str,
        url: str | None = None,
        steps: list[dict[str, str]] | None = None,
        width: int = DEFAULT_SCREENSHOT_WIDTH,
        height: int = DEFAULT_SCREENSHOT_HEIGHT,
    ) -> dict[str, Any]:
        """Capture a UI screenshot for a named user scenario."""
        ctx.deps.tool_calls += 1
        result = capture_browser_screenshot(
            config=ctx.deps.browser,
            evidence=ctx.deps.evidence,
            scenario=scenario,
            url=url,
            steps=steps or [],
            width=width,
            height=height,
        )
        return result


def capture_browser_screenshot(
    *,
    config: BrowserToolConfig,
    evidence: EvidenceBundle,
    scenario: str,
    url: str | None,
    steps: list[dict[str, str]],
    width: int,
    height: int,
) -> dict[str, Any]:
    if not config.enabled:
        return {"ok": False, "error": "Browser screenshot tool is disabled."}

    target_url = url or config.base_url
    if not target_url:
        return {
            "ok": False,
            "error": "Browser URL is required. Pass url or configure GUIDESYNC_BROWSER_BASE_URL.",
        }

    config.screenshot_dir.mkdir(parents=True, exist_ok=True)
    path = screenshot_path(config.screenshot_dir, scenario)
    if sync_playwright is not None:
        return capture_with_playwright(
            evidence=evidence,
            scenario=scenario,
            target_url=target_url,
            steps=steps,
            path=path,
            width=width,
            height=height,
            timeout_ms=config.timeout_ms,
        )

    if steps:
        return {
            "ok": False,
            "error": (
                "Playwright is not installed, so scenario steps cannot be executed. "
                "Install Playwright or call this tool with no interaction steps."
            ),
        }
    return capture_with_chrome_cli(
        evidence=evidence,
        scenario=scenario,
        target_url=target_url,
        path=path,
        width=width,
        height=height,
        timeout_ms=config.timeout_ms,
    )


def capture_with_playwright(
    *,
    evidence: EvidenceBundle,
    scenario: str,
    target_url: str,
    steps: list[dict[str, str]],
    path: Path,
    width: int,
    height: int,
    timeout_ms: int,
) -> dict[str, Any]:
    playwright_runner = sync_playwright
    if playwright_runner is None:
        return {"ok": False, "error": "Playwright is not installed."}
    try:
        with playwright_runner() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(target_url, wait_until="networkidle", timeout=timeout_ms)
            for step in steps:
                execute_browser_step(page, step, timeout_ms)
            page.screenshot(path=str(path), full_page=True)
            browser.close()
    except Exception as exc:  # noqa: BLE001 - return tool error to the agent
        return {"ok": False, "error": f"Browser screenshot failed: {exc}"}
    return record_screenshot(evidence, scenario, target_url, path, "Captured with Playwright.")


def capture_with_chrome_cli(
    *,
    evidence: EvidenceBundle,
    scenario: str,
    target_url: str,
    path: Path,
    width: int,
    height: int,
    timeout_ms: int,
) -> dict[str, Any]:
    browser = find_browser_binary()
    if browser is None:
        return {
            "ok": False,
            "error": "No browser binary was found and Playwright is not installed.",
        }
    completed = subprocess.run(
        [
            browser,
            "--headless=new",
            "--disable-gpu",
            f"--screenshot={path}",
            f"--window-size={width},{height}",
            f"--timeout={timeout_ms}",
            target_url,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=max(5, int(timeout_ms / 1000) + 5),
    )
    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip() or "Browser exited non-zero."
        return {
            "ok": False,
            "error": error,
        }
    return record_screenshot(evidence, scenario, target_url, path, "Captured with browser CLI.")


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
    evidence: EvidenceBundle,
    scenario: str,
    target_url: str,
    path: Path,
    notes: str,
) -> dict[str, Any]:
    screenshot = BrowserScreenshotEvidence(
        scenario=scenario,
        url=target_url,
        path=str(path),
        notes=notes,
    )
    evidence.browser_screenshots.append(screenshot)
    return {
        "ok": True,
        "scenario": scenario,
        "url": target_url,
        "path": str(path),
        "notes": notes,
    }


def screenshot_path(directory: Path, scenario: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", scenario.strip().lower()).strip("-")
    name = safe or "ui-screenshot"
    path = directory / f"{name}.png"
    counter = 2
    while path.exists():
        path = directory / f"{name}-{counter}.png"
        counter += 1
    return path


def find_browser_binary() -> str | None:
    candidates = [
        os.environ.get("GUIDESYNC_BROWSER_BINARY"),
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
