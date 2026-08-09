from __future__ import annotations

import time
from importlib import import_module
from typing import Any

from pydantic_ai import RunContext

from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    EvidenceBundle,
    ProviderConfig,
    ReportLocale,
    ScreenshotCaptureResult,
    ScreenshotPlanItem,
    ScreenshotTheme,
    ScreenshotViewport,
)
from guidesync_agent.services.screenshot_validation import (
    finalize_screenshot_capture,
    validate_screenshot_capture,
)
from guidesync_agent.services.stable_ids import stable_id
from guidesync_agent.settings import BrowserToolSettings, get_settings
from guidesync_agent.tools.browser_evidence import (
    browser_capture_failure,
    browser_policy_audit,
    browser_policy_audit_from_config,
    dump_browser_capture,
    record_screenshot,
    replace_evidence_capture,
)
from guidesync_agent.tools.browser_models import (
    BrowserCaptureContext,
    BrowserCaptureDiagnostics,
    BrowserCaptureErrorCode,
    BrowserCaptureEvents,
    BrowserCaptureFailure,
    BrowserScreenshotRequest,
)
from guidesync_agent.tools.browser_support import (
    allowed_target_url,
    bounded_text,
    capture_prepared_image,
    ensure_allowed_page_origin,
    execute_browser_step,
    origin,
    parse_browser_step,
    read_aria_snapshot,
    redact_snapshot,
    screenshot_actions_for_steps,
    screenshot_path,
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
        capture_target: str = "viewport",
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
