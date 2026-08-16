from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from guidesync_agent.schemas import (
    ScreenshotAction,
    ScreenshotActionKind,
    ScreenshotCropRecord,
    ScreenshotLocatorKind,
    ScreenshotMaskRecord,
)
from guidesync_agent.settings import get_settings
from guidesync_agent.tools.browser_models import (
    BrowserCaptureContext,
    BrowserPreparedImage,
)

BROWSER_NAVIGATION_SETTLE_MS = 1_000


def parse_browser_step(step: str) -> dict[str, str]:
    stripped = step.strip()
    action, _, rest = stripped.partition(" ")
    action = action.strip().lower()
    rest = rest.strip()
    if action == "goto":
        return {"action": action, "value": rest}
    if action in {"click", "wait_for"}:
        return {"action": action, **parse_semantic_locator(rest)}
    if action == "wait":
        return {"action": action, "value": rest}
    raise ValueError(f"Unsupported browser step: {step}")


def screenshot_actions_for_steps(steps: list[str]) -> list[ScreenshotAction]:
    actions: list[ScreenshotAction] = []
    for raw_step in steps[:8]:
        step = parse_browser_step(raw_step)
        action = step["action"]
        if action == "goto":
            actions.append(
                ScreenshotAction(
                    kind=ScreenshotActionKind.NAVIGATE,
                    route=step["value"],
                )
            )
            continue
        if action == "wait":
            wait_ms = min(max(int(step["value"] or "1000"), 0), 5_000)
            actions.append(ScreenshotAction(kind=ScreenshotActionKind.WAIT, wait_ms=wait_ms))
            continue
        locator_kind = ScreenshotLocatorKind(
            "test_id" if step["locator_kind"] == "testid" else step["locator_kind"]
        )
        actions.append(
            ScreenshotAction(
                kind=(
                    ScreenshotActionKind.CLICK
                    if action == "click"
                    else ScreenshotActionKind.WAIT_FOR
                ),
                locator_kind=locator_kind,
                locator=step["locator"],
                role_name=step.get("role_name"),
            )
        )
    return actions


def execute_browser_step(
    page: Any,
    step: dict[str, str],
    timeout_ms: int,
    *,
    allowed_origin: str,
) -> None:
    action = step.get("action", "").strip().lower()
    value = step.get("value", "")
    if action == "goto":
        target = allowed_target_url(allowed_origin, value)
        if target is None:
            raise ValueError("goto action is outside the configured interface origin")
        navigate_browser_page(page, target, timeout_ms)
        ensure_allowed_page_origin(page, allowed_origin)
        return
    if action == "click":
        semantic_locator(page, step).click(timeout=timeout_ms)
        ensure_allowed_page_origin(page, allowed_origin)
        page.wait_for_timeout(min(BROWSER_NAVIGATION_SETTLE_MS, timeout_ms))
        return
    if action == "wait_for":
        semantic_locator(page, step).filter(visible=True).first.wait_for(
            state="visible",
            timeout=timeout_ms,
        )
        return
    if action == "wait":
        wait_ms = min(max(int(value or "1000"), 0), 5_000)
        page.wait_for_timeout(wait_ms)
        return
    raise ValueError(f"Unsupported browser step: {step}")


def navigate_browser_page(page: Any, target: str, timeout_ms: int) -> None:
    page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(min(BROWSER_NAVIGATION_SETTLE_MS, timeout_ms))


def ensure_allowed_page_origin(page: Any, allowed_origin: str) -> None:
    if origin(page.url) != allowed_origin:
        raise ValueError("browser interaction left the configured interface origin")


def parse_semantic_locator(value: str) -> dict[str, str]:
    kind, separator, locator = value.partition("=")
    kind = kind.strip().lower()
    locator = strip_locator_quotes(locator)
    if not separator or kind not in {"role", "label", "text", "testid"} or not locator:
        raise ValueError(
            "Browser locators must use role=, label=, text=, or testid= semantic syntax."
        )
    if kind == "role":
        role, name_separator, name = locator.partition(" name=")
        payload = {"locator_kind": kind, "locator": strip_locator_quotes(role)}
        if name_separator and strip_locator_quotes(name):
            payload["role_name"] = strip_locator_quotes(name)
        return payload
    return {"locator_kind": kind, "locator": locator}


def strip_locator_quotes(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1].strip()
    return stripped


def semantic_locator(page: Any, step: dict[str, str]) -> Any:
    kind = step.get("locator_kind")
    value = step.get("locator", "")
    if kind == "role":
        name = step.get("role_name")
        return page.get_by_role(value, name=name) if name else page.get_by_role(value)
    if kind == "label":
        return page.get_by_label(value)
    if kind == "text":
        return page.get_by_text(value, exact=True)
    if kind == "testid":
        return page.get_by_test_id(value)
    raise ValueError("Unsupported semantic locator.")


def allowed_target_url(base_url: str | None, requested_url: str | None) -> str | None:
    if not base_url and not requested_url:
        return None
    allowed = origin(base_url or requested_url or "")
    if not allowed:
        return None
    target = urljoin(f"{allowed}/", requested_url or base_url or "")
    return target if origin(target) == allowed else None


def origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def route_for_url(url: str) -> str:
    parsed = urlparse(url)
    route = parsed.path or "/"
    if parsed.query:
        route += f"?{parsed.query}"
    if parsed.fragment:
        route += f"#{parsed.fragment}"
    return route


def capture_prepared_image(page: Any, context: BrowserCaptureContext) -> BrowserPreparedImage:
    target = context.plan_item.capture_target if context.plan_item else "viewport"
    mask_locators, masks = privacy_mask_targets(page)
    screenshot_options = {
        "mask": mask_locators,
        "mask_color": "#718985",
    }
    if target == "viewport":
        page.screenshot(path=str(context.path), full_page=False, **screenshot_options)
        return BrowserPreparedImage(
            crop=ScreenshotCropRecord(
                mode="viewport",
                width=float(context.width),
                height=float(context.height),
            ),
            masks=masks,
        )
    locator = semantic_locator(page, parse_semantic_locator(target))
    locator.scroll_into_view_if_needed(timeout=context.timeout_ms)
    if target.startswith("text="):
        page.screenshot(path=str(context.path), full_page=False, **screenshot_options)
        return BrowserPreparedImage(
            crop=ScreenshotCropRecord(
                mode="viewport-target",
                width=float(context.width),
                height=float(context.height),
            ),
            masks=masks,
        )
    box = locator.bounding_box() or {}
    if target == "role=main":
        padding = locator.evaluate(
            """node => {
              const style = getComputedStyle(node);
              return {
                bottom: style.paddingBottom,
                left: style.paddingLeft,
                right: style.paddingRight,
                top: style.paddingTop
              };
            }"""
        )
        clip = bounded_content_clip(box, padding, context.viewport)
        page.screenshot(
            path=str(context.path),
            full_page=False,
            clip=clip,
            **screenshot_options,
        )
        return BrowserPreparedImage(
            crop=ScreenshotCropRecord(mode="element-content", **clip),
            masks=masks,
        )
    locator.screenshot(path=str(context.path), **screenshot_options)
    return BrowserPreparedImage(
        crop=ScreenshotCropRecord(
            mode="element",
            x=box.get("x"),
            y=box.get("y"),
            width=box.get("width"),
            height=box.get("height"),
        ),
        masks=masks,
    )


def bounded_content_clip(
    box: dict[str, float],
    padding: dict[str, str],
    viewport: dict[str, int],
) -> dict[str, float]:
    left = css_pixels(padding.get("left"))
    right = css_pixels(padding.get("right"))
    top = css_pixels(padding.get("top"))
    bottom = css_pixels(padding.get("bottom"))
    x = max(float(box.get("x", 0)) + left, 0)
    y = max(float(box.get("y", 0)) + top, 0)
    content_width = max(float(box.get("width", viewport["width"])) - left - right, 1)
    content_height = max(float(box.get("height", viewport["height"])) - top - bottom, 1)
    return {
        "x": x,
        "y": y,
        "width": min(content_width, max(float(viewport["width"]) - x, 1)),
        "height": min(content_height, max(float(viewport["height"]) - y, 1)),
    }


def css_pixels(value: str | None) -> float:
    if not value or not value.endswith("px"):
        return 0
    try:
        return max(float(value.removesuffix("px")), 0)
    except ValueError:
        return 0


def privacy_mask_values(text: str) -> list[str]:
    return [value for value, _ in privacy_mask_candidates(text)]


def privacy_mask_candidates(text: str) -> list[tuple[str, str]]:
    internal_id_pattern = re.compile(
        r"\b(?:artifact|change|claim|llm-conv|profile|project|run|scenario|workflow-task)"
        r"-[0-9a-f]{8,}\b",
        flags=re.IGNORECASE,
    )
    email_pattern = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
    credential_pattern = re.compile(
        r"\b(?:bearer\s+\S+|(?:api[_ -]?key|token|password)\s*[:=]\s*\S+)",
        flags=re.IGNORECASE,
    )
    uuid_pattern = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", flags=re.IGNORECASE)
    private_url_pattern = re.compile(
        r"https?://(?:localhost|127\.0\.0\.1|host\.docker\.internal|[^\s/]+\.internal)\S*",
        flags=re.IGNORECASE,
    )
    candidates = [
        *((value, "private_email") for value in email_pattern.findall(text)),
        *((value, "credential") for value in credential_pattern.findall(text)),
        *((value, "internal_identifier") for value in internal_id_pattern.findall(text)),
        *((value, "internal_identifier") for value in uuid_pattern.findall(text)),
        *((value, "private_url") for value in private_url_pattern.findall(text)),
    ]
    return list(dict.fromkeys(candidates))[:12]


def privacy_mask_targets(page: Any) -> tuple[list[Any], list[ScreenshotMaskRecord]]:
    candidates = privacy_mask_candidates(page.locator("body").inner_text(timeout=1_000))
    locators: list[Any] = []
    records: list[ScreenshotMaskRecord] = []
    for value, reason in candidates:
        locator = page.get_by_text(value, exact=True)
        if not locator.count():
            continue
        locators.append(locator)
        records.append(
            ScreenshotMaskRecord(
                reason=reason,
                locator_kind=ScreenshotLocatorKind.TEXT,
                locator=value,
            )
        )
    return locators, records


def read_aria_snapshot(locator: Any) -> str:
    try:
        return locator.aria_snapshot(timeout=1_000)
    except Exception:  # noqa: BLE001 - ARIA snapshot is optional capture metadata
        return ""


def bounded_text(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 3]}..."


def redact_snapshot(value: str) -> str:
    patterns = (
        (r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted-email]"),
        (r"(?i)(bearer|api[_ -]?key|token|password)(\s*[:=]\s*)\S+", r"\1\2[redacted]"),
        (r"https?://(?:localhost|127\.0\.0\.1|host\.docker\.internal)\S*", "[redacted-url]"),
    )
    redacted = value
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


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
