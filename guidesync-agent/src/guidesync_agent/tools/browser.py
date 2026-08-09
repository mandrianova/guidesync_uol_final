from __future__ import annotations

import hashlib
import re
import shutil
import time
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from pydantic_ai import RunContext

from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    EvidenceBundle,
    OperationError,
    ProviderConfig,
    ReportLocale,
    ScreenshotAction,
    ScreenshotActionKind,
    ScreenshotCaptureResult,
    ScreenshotCropRecord,
    ScreenshotLocatorKind,
    ScreenshotMaskRecord,
    ScreenshotPlanItem,
    ScreenshotPolicyAudit,
    ScreenshotTheme,
    ScreenshotViewport,
)
from guidesync_agent.services.screenshot_validation import (
    finalize_screenshot_capture,
    validate_screenshot_capture,
)
from guidesync_agent.services.stable_ids import stable_id
from guidesync_agent.settings import BrowserToolSettings, get_settings
from guidesync_agent.tools.browser_models import (
    BrowserCaptureContext,
    BrowserCaptureDiagnostics,
    BrowserCaptureErrorCode,
    BrowserCaptureEvents,
    BrowserCaptureFailure,
    BrowserPreparedImage,
    BrowserScreenshotRequest,
)
from guidesync_agent.tools.registry import (
    DEFAULT_TOOL_REGISTRY_ID,
    PYDANTIC_AI_TOOL_DEFINITIONS,
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
        change_id: str,
        claim: str,
        route: str,
        expected_text: list[str],
        rejected_text: list[str],
        caption: str,
        alt_text: str,
        evidence_refs: list[str],
        actions: list[str] | None = None,
        theme: str = "light",
        capture_target: str = "role=main",
        width: int = DEFAULT_SCREENSHOT_WIDTH,
        height: int = DEFAULT_SCREENSHOT_HEIGHT,
    ) -> dict[str, Any]:
        """Capture one bounded public no-auth UI evidence scenario."""
        ctx.deps.tool_calls += 1
        claim_id = stable_id("claim", change_id, claim)
        scenario_id = stable_id("scenario", change_id, route, claim)
        bounded_actions = (actions or [])[:8]
        try:
            typed_actions = screenshot_actions_for_steps(bounded_actions)
        except ValueError as exc:
            return dump_browser_capture(
                browser_capture_failure(
                    BrowserCaptureErrorCode.INVALID_ACTION,
                    str(exc),
                    policy_audit=browser_policy_audit_from_config(
                        ctx.deps.browser,
                        "denied",
                    ),
                )
            )
        item = ScreenshotPlanItem(
            id=scenario_id,
            change_id=change_id,
            claim_id=claim_id,
            claim=claim,
            route=route,
            actions=typed_actions,
            expected_text=expected_text[:8],
            rejected_text=rejected_text[:8],
            requested_state=claim,
            viewport=ScreenshotViewport(width=width, height=height),
            theme=ScreenshotTheme(theme),
            capture_target=capture_target,
            caption=caption,
            alt_text=alt_text,
            evidence_refs=evidence_refs[:12],
        )
        result = capture_browser_screenshot(
            ctx.deps.browser,
            ctx.deps.evidence,
            BrowserScreenshotRequest(
                scenario=scenario_id,
                url=route,
                steps=bounded_actions,
                width=width,
                height=height,
                expected_text=expected_text[:8],
                rejected_text=rejected_text[:8],
                plan_item=item,
            ),
        )
        if result.get("error") is not None:
            return result
        capture = ScreenshotCaptureResult.model_validate(result)
        validation = validate_screenshot_capture(
            capture,
            item.expected_text,
            rejected_text=item.rejected_text,
            locale=ReportLocale(ctx.deps.report_locale),
        )
        finalized = finalize_screenshot_capture(capture, [validation])
        replace_evidence_capture(ctx.deps.evidence, finalized)
        return finalized.model_dump(mode="json")


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
                policy_audit=browser_policy_audit_from_config(config, "denied"),
            )
        )

    target_url = allowed_target_url(config.base_url, request.url)
    if target_url is None:
        return dump_browser_capture(
            browser_capture_failure(
                BrowserCaptureErrorCode.ORIGIN_DENIED,
                "Browser navigation must stay within the configured interface origin.",
                policy_audit=browser_policy_audit_from_config(config, "denied"),
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
        rejected_text=request.rejected_text,
        plan_item=request.plan_item,
        browser_binary=config.binary,
    )
    if sync_playwright is not None:
        return dump_browser_capture(capture_with_playwright(context))

    return dump_browser_capture(
        browser_capture_failure(
            BrowserCaptureErrorCode.PLAYWRIGHT_UNAVAILABLE,
            "Playwright is required for bounded same-origin screenshot capture.",
            policy_audit=browser_policy_audit(context, decision="denied"),
        )
    )


def capture_with_playwright(
    context: BrowserCaptureContext,
) -> BrowserScreenshotEvidence | BrowserCaptureFailure:
    playwright_runner = sync_playwright
    if playwright_runner is None:
        return browser_capture_failure(
            BrowserCaptureErrorCode.PLAYWRIGHT_UNAVAILABLE,
            "Playwright is not installed.",
            policy_audit=browser_policy_audit(context, decision="denied"),
        )
    started = time.perf_counter()
    try:
        with playwright_runner() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": context.width, "height": context.height}
            )
            if context.plan_item and context.plan_item.theme is not ScreenshotTheme.SYSTEM:
                page.emulate_media(color_scheme=context.plan_item.theme.value)
            events = BrowserCaptureEvents()
            register_browser_capture_events(page, events)
            page.goto(
                context.target_url,
                wait_until="networkidle",
                timeout=context.timeout_ms,
            )
            ensure_allowed_page_origin(page, origin(context.target_url))
            for step in context.steps:
                execute_browser_step(
                    page,
                    parse_browser_step(step),
                    context.timeout_ms,
                    allowed_origin=origin(context.target_url),
                )
            ensure_allowed_page_origin(page, origin(context.target_url))
            diagnostics = complete_playwright_capture(
                page,
                context,
                events,
                browser_version=browser.version,
                started=started,
            )
            browser.close()
    except Exception as exc:  # noqa: BLE001 - return tool error to the agent
        return browser_capture_failure(
            BrowserCaptureErrorCode.CAPTURE_FAILED,
            f"Browser screenshot failed: {exc}",
            retryable=True,
            policy_audit=browser_policy_audit(context, decision="failed"),
        )
    return record_screenshot(context, diagnostics)


def register_browser_capture_events(page: Any, events: BrowserCaptureEvents) -> None:
    page.on(
        "console",
        lambda message: events.console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on(
        "requestfailed",
        lambda request: events.network_errors.append(request.url),
    )
    page.on("pageerror", lambda error: events.page_errors.append(str(error)))


def complete_playwright_capture(
    page: Any,
    context: BrowserCaptureContext,
    events: BrowserCaptureEvents,
    *,
    browser_version: str,
    started: float,
) -> BrowserCaptureDiagnostics:
    body = page.locator("body")
    dom_snapshot = bounded_text(body.evaluate("node => node.outerHTML"), 16_000)
    aria_snapshot = bounded_text(read_aria_snapshot(body), 12_000)
    page.screenshot(path=str(context.raw_path), full_page=True)
    build_identity_locator = page.locator(
        'meta[name="application-version"], meta[name="build-id"]'
    )
    build_identity = (
        build_identity_locator.first.get_attribute("content")
        if build_identity_locator.count()
        else None
    )
    prepared = capture_prepared_image(page, context)
    return BrowserCaptureDiagnostics(
        notes="Captured with Playwright.",
        title=page.title(),
        visible_text=bounded_text(body.inner_text(timeout=1000), 12_000),
        console_errors=events.console_errors,
        network_errors=events.network_errors,
        page_errors=events.page_errors,
        failed_requests=events.network_errors,
        final_url=page.url,
        dom_snapshot=redact_snapshot(dom_snapshot),
        aria_snapshot=redact_snapshot(aria_snapshot),
        browser_identity=f"chromium/{browser_version}",
        build_identity=build_identity,
        duration_ms=int((time.perf_counter() - started) * 1000),
        crop=prepared.crop,
        masks=prepared.masks,
    )


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
        page.goto(target, wait_until="networkidle", timeout=timeout_ms)
        ensure_allowed_page_origin(page, allowed_origin)
        return
    if action == "click":
        semantic_locator(page, step).click(timeout=timeout_ms)
        ensure_allowed_page_origin(page, allowed_origin)
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


def ensure_allowed_page_origin(page: Any, allowed_origin: str) -> None:
    if origin(page.url) != allowed_origin:
        raise ValueError("browser interaction left the configured interface origin")


def parse_semantic_locator(value: str) -> dict[str, str]:
    kind, separator, locator = value.partition("=")
    kind = kind.strip().lower()
    locator = locator.strip()
    if not separator or kind not in {"role", "label", "text", "testid"} or not locator:
        raise ValueError(
            "Browser locators must use role=, label=, text=, or testid= semantic syntax."
        )
    if kind == "role":
        role, name_separator, name = locator.partition(" name=")
        payload = {"locator_kind": kind, "locator": role.strip()}
        if name_separator and name.strip():
            payload["role_name"] = name.strip()
        return payload
    return {"locator_kind": kind, "locator": locator}


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
    pattern = re.compile(
        r"\b(?:artifact|change|claim|llm-conv|profile|project|run|scenario|workflow-task)"
        r"-[0-9a-f]{8,}\b",
        flags=re.IGNORECASE,
    )
    return list(dict.fromkeys(pattern.findall(text)))[:12]


def privacy_mask_targets(page: Any) -> tuple[list[Any], list[ScreenshotMaskRecord]]:
    values = privacy_mask_values(page.locator("body").inner_text(timeout=1_000))
    locators: list[Any] = []
    records: list[ScreenshotMaskRecord] = []
    for value in values:
        locator = page.get_by_text(value, exact=True).first
        if not locator.count():
            continue
        locators.append(locator)
        records.append(
            ScreenshotMaskRecord(
                reason="internal_identifier",
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


def browser_policy_audit(
    context: BrowserCaptureContext,
    *,
    decision: str = "allowed",
) -> ScreenshotPolicyAudit:
    definition = PYDANTIC_AI_TOOL_DEFINITIONS["capture_ui_screenshot"]
    return ScreenshotPolicyAudit(
        registry_id=DEFAULT_TOOL_REGISTRY_ID,
        permission=definition.permission.value,
        risk=definition.risk.value,
        resource_scope=definition.scope.value,
        decision=decision,
        timeout_ms=context.timeout_ms,
        output_limit_chars=definition.max_output_chars,
        retry_policy=definition.retry_policy,
    )


def browser_policy_audit_from_config(
    config: BrowserToolConfig,
    decision: str,
) -> ScreenshotPolicyAudit:
    definition = PYDANTIC_AI_TOOL_DEFINITIONS["capture_ui_screenshot"]
    return ScreenshotPolicyAudit(
        registry_id=DEFAULT_TOOL_REGISTRY_ID,
        permission=definition.permission.value,
        risk=definition.risk.value,
        resource_scope=definition.scope.value,
        decision=decision,
        timeout_ms=config.timeout_ms,
        output_limit_chars=definition.max_output_chars,
        retry_policy=definition.retry_policy,
    )


def text_hash(value: str) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def record_screenshot(
    context: BrowserCaptureContext,
    diagnostics: BrowserCaptureDiagnostics,
) -> BrowserScreenshotEvidence:
    image_hash = file_hash(context.path)
    raw_hash = file_hash(context.raw_path)
    blank = is_blank_screenshot(context.path)
    matched_text = [
        item
        for item in context.expected_text
        if item.lower() in diagnostics.visible_text.lower()
    ]
    missing_text = [item for item in context.expected_text if item not in matched_text]
    matched_rejected = [
        item
        for item in context.rejected_text
        if item.lower() in diagnostics.visible_text.lower()
    ]
    item = context.plan_item
    final_url = diagnostics.final_url or context.target_url
    screenshot = BrowserScreenshotEvidence(
        scenario=context.scenario,
        url=final_url,
        path=str(context.path),
        title=diagnostics.title,
        viewport=context.viewport,
        visible_text=diagnostics.visible_text,
        matched_text=matched_text,
        missing_text=missing_text,
        console_errors=diagnostics.console_errors,
        network_errors=diagnostics.network_errors,
        page_errors=diagnostics.page_errors,
        failed_requests=diagnostics.failed_requests,
        image_hash=image_hash,
        raw_image_hash=raw_hash,
        prepared_image_hash=image_hash,
        blank=blank,
        notes=diagnostics.notes,
        capture_id=stable_id("capture", context.scenario, final_url, str(context.path)),
        scenario_id=item.id if item else context.scenario,
        plan_item_id=item.id if item else None,
        change_id=item.change_id if item else None,
        claim_id=item.claim_id if item else None,
        route=route_for_url(final_url),
        theme=item.theme if item else ScreenshotTheme.LIGHT,
        requested_state=item.requested_state if item else "",
        observed_state=diagnostics.title or "",
        rejected_text=context.rejected_text,
        matched_rejected_text=matched_rejected,
        dom_snapshot=diagnostics.dom_snapshot,
        dom_hash=text_hash(diagnostics.dom_snapshot),
        aria_snapshot=diagnostics.aria_snapshot,
        aria_hash=text_hash(diagnostics.aria_snapshot),
        browser_identity=diagnostics.browser_identity,
        build_identity=diagnostics.build_identity,
        raw_path=str(context.raw_path),
        raw_artifact_name=context.raw_path.name,
        prepared_artifact_name=context.path.name,
        crop=diagnostics.crop,
        masks=diagnostics.masks,
        caption=item.caption if item else "",
        alt_text=item.alt_text if item else "",
        capture_target=item.capture_target if item else "viewport",
        duration_ms=diagnostics.duration_ms,
        policy_audit=browser_policy_audit(context),
        plan_item=item,
    )
    context.evidence.browser_screenshots.append(screenshot)
    return screenshot


def replace_evidence_capture(
    evidence: EvidenceBundle,
    capture: ScreenshotCaptureResult,
) -> None:
    screenshot = BrowserScreenshotEvidence.from_capture(
        capture,
        notes="Captured by the bounded release-notes browser tool.",
    )
    index = next(
        (
            item_index
            for item_index, item in enumerate(evidence.browser_screenshots)
            if item.path == capture.path or item.capture_id == capture.capture_id
        ),
        None,
    )
    if index is None:
        evidence.browser_screenshots.append(screenshot)
    else:
        evidence.browser_screenshots[index] = screenshot


def browser_capture_failure(
    code: BrowserCaptureErrorCode,
    message: str,
    *,
    retryable: bool = False,
    policy_audit: ScreenshotPolicyAudit | None = None,
) -> BrowserCaptureFailure:
    return BrowserCaptureFailure(
        error=OperationError(
            code=code.value,
            message=message,
            retryable=retryable,
        ),
        policy_audit=policy_audit,
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
