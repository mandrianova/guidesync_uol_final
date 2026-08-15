from __future__ import annotations

import json
import time
from dataclasses import dataclass
from importlib import import_module
from typing import Any, cast

from pydantic import SecretStr
from pydantic_ai import RunContext

from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    EvidenceBundle,
    ProviderConfig,
    ReportLocale,
    ScreenshotAction,
    ScreenshotCaptureResult,
    ScreenshotPlanItem,
    ScreenshotTheme,
    ScreenshotViewport,
    TaskInterfaceAuthType,
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
    navigate_browser_page,
    origin,
    parse_browser_step,
    read_aria_snapshot,
    redact_snapshot,
    screenshot_actions_for_steps,
    screenshot_path,
)


@dataclass(frozen=True)
class PreparedAgentScreenshot:
    attempt_signature: str
    plan_item: ScreenshotPlanItem
    request: BrowserScreenshotRequest

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
    def inspect_ui(
        ctx: RunContext[Any],
        route: str,
        actions: list[str] | None = None,
        width: int = DEFAULT_SCREENSHOT_WIDTH,
        height: int = DEFAULT_SCREENSHOT_HEIGHT,
    ) -> dict[str, Any]:
        """Inspect bounded UI state after optional same-origin semantic actions."""
        return inspect_agent_ui(ctx, route, actions=actions, width=width, height=height)

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
        """Capture one bounded same-origin UI scenario; vary failed retries."""
        return capture_agent_screenshot(
            ctx,
            change_id=change_id,
            claim=claim,
            route=route,
            expected_text=expected_text,
            rejected_text=rejected_text,
            caption=caption,
            alt_text=alt_text,
            evidence_refs=evidence_refs,
            actions=actions,
            theme=theme,
            capture_target=capture_target,
            width=width,
            height=height,
        )


def inspect_agent_ui(
    ctx: RunContext[Any],
    route: str,
    *,
    actions: list[str] | None,
    width: int,
    height: int,
) -> dict[str, Any]:
    ctx.deps.tool_calls += 1
    effective_route = allowed_target_url(ctx.deps.browser.base_url, route) or route
    bounded_actions = (actions or [])[:8]
    try:
        parsed_actions = [parse_browser_step(action) for action in bounded_actions]
    except ValueError as exc:
        return invalid_capture_plan(ctx, str(exc), tool_name="inspect_ui")
    signature = stable_id(
        "ui-inspection",
        effective_route,
        *bounded_actions,
        str(width),
        str(height),
    )
    if signature in ctx.deps.ui_inspection_signatures:
        return invalid_capture_plan(
            ctx,
            "Duplicate UI inspection. Change the route or viewport, or use the prior bounded "
            "visible-text and ARIA result to choose the next action.",
            retryable=True,
            tool_name="inspect_ui",
        )
    result = inspect_browser_ui(
        ctx.deps.browser,
        effective_route,
        actions=parsed_actions,
        width=width,
        height=height,
    )
    if result.get("error") is None:
        ctx.deps.ui_inspection_signatures.add(signature)
    return result


def capture_agent_screenshot(  # noqa: PLR0913 - mirrors the model-facing tool schema
    ctx: RunContext[Any],
    *,
    change_id: str,
    claim: str,
    route: str,
    expected_text: list[str],
    rejected_text: list[str],
    caption: str,
    alt_text: str,
    evidence_refs: list[str],
    actions: list[str] | None,
    theme: str,
    capture_target: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    ctx.deps.tool_calls += 1
    prepared = prepare_agent_screenshot(
        ctx,
        change_id=change_id,
        claim=claim,
        route=route,
        expected_text=expected_text,
        rejected_text=rejected_text,
        caption=caption,
        alt_text=alt_text,
        evidence_refs=evidence_refs,
        actions=actions,
        theme=theme,
        capture_target=capture_target,
        width=width,
        height=height,
    )
    if isinstance(prepared, dict):
        return cast(dict[str, Any], prepared)
    ctx.deps.screenshot_attempt_signatures.add(prepared.attempt_signature)
    result = capture_browser_screenshot(
        ctx.deps.browser,
        ctx.deps.evidence,
        prepared.request,
    )
    if result.get("error") is not None:
        return result
    return validate_agent_screenshot(ctx, prepared.plan_item, result)


def prepare_agent_screenshot(  # noqa: PLR0913 - mirrors the model-facing tool schema
    ctx: RunContext[Any],
    *,
    change_id: str,
    claim: str,
    route: str,
    expected_text: list[str],
    rejected_text: list[str],
    caption: str,
    alt_text: str,
    evidence_refs: list[str],
    actions: list[str] | None,
    theme: str,
    capture_target: str,
    width: int,
    height: int,
) -> PreparedAgentScreenshot | dict[str, Any]:
    if change_id_issue := screenshot_change_id_issue(ctx, change_id):
        return invalid_capture_plan(ctx, change_id_issue)
    planned_evidence_refs = ctx.deps.screenshot_candidate_evidence_refs.get(change_id)
    if planned_evidence_refs is not None:
        evidence_refs = planned_evidence_refs
    bounded_actions = (actions or [])[:8]
    try:
        typed_actions = screenshot_actions_for_steps(bounded_actions)
    except ValueError as exc:
        return invalid_capture_plan(ctx, str(exc))
    visible_text = expected_visible_text(expected_text, typed_actions)
    bounded_rejected_text = rejected_text[:8]
    effective_route = allowed_target_url(ctx.deps.browser.base_url, route) or route
    attempt_signature = screenshot_attempt_signature(
        change_id=change_id,
        claim=claim,
        route=effective_route,
        expected_text=visible_text,
        rejected_text=bounded_rejected_text,
        actions=typed_actions,
        theme=theme,
        capture_target=capture_target,
        width=width,
        height=height,
    )
    if attempt_signature in ctx.deps.screenshot_attempt_signatures:
        return invalid_capture_plan(
            ctx,
            "Duplicate screenshot attempt. Change the route, viewport, actions, state, or "
            "evidence-grounded text before retrying.",
            retryable=True,
        )
    claim_id = stable_id("claim", change_id, claim)
    scenario_id = stable_id("scenario", change_id, effective_route, claim, attempt_signature)
    try:
        item = ScreenshotPlanItem(
            id=scenario_id,
            change_id=change_id,
            claim_id=claim_id,
            claim=claim,
            route=effective_route,
            actions=typed_actions,
            expected_text=visible_text,
            rejected_text=bounded_rejected_text,
            requested_state=claim,
            viewport=ScreenshotViewport(width=width, height=height),
            theme=ScreenshotTheme(theme),
            capture_target=capture_target,
            caption=caption,
            alt_text=alt_text,
            evidence_refs=evidence_refs[:12],
        )
    except ValueError as exc:
        return invalid_capture_plan(ctx, f"Invalid screenshot plan: {exc}")
    return PreparedAgentScreenshot(
        attempt_signature=attempt_signature,
        plan_item=item,
        request=BrowserScreenshotRequest(
            scenario=scenario_id,
            url=effective_route,
            steps=bounded_actions,
            width=width,
            height=height,
            expected_text=visible_text,
            rejected_text=bounded_rejected_text,
            plan_item=item,
        ),
    )


def screenshot_change_id_issue(ctx: RunContext[Any], change_id: str) -> str | None:
    allowed_change_ids = set(ctx.deps.screenshot_candidate_change_ids)
    if allowed_change_ids and change_id not in allowed_change_ids:
        return "Screenshot change_id must match a planned screenshot request."
    if ctx.deps.analysis_manifest is not None and change_id not in {
        artifact.id for artifact in ctx.deps.analysis_manifest.artifacts
    }:
        return "Screenshot change_id must be an exact id from the analysis manifest."
    return None


def invalid_capture_plan(
    ctx: RunContext[Any],
    message: str,
    *,
    retryable: bool = False,
    tool_name: str = "capture_ui_screenshot",
) -> dict[str, Any]:
    return dump_browser_capture(
        browser_capture_failure(
            BrowserCaptureErrorCode.INVALID_ACTION,
            message,
            retryable=retryable,
            policy_audit=browser_policy_audit_from_config(
                ctx.deps.browser,
                "denied",
                tool_name=tool_name,
            ),
        )
    )


def validate_agent_screenshot(
    ctx: RunContext[Any],
    item: ScreenshotPlanItem,
    result: dict[str, Any],
) -> dict[str, Any]:
    # Imported here to avoid the browser -> agent_runtime -> release_notes cycle.
    from guidesync_agent.agent_runtime.screenshot_model_usage import (
        ScreenshotModelUsageContext,
        record_screenshot_model_usage,
    )
    from guidesync_agent.services.ui_evidence.validation import (
        default_screenshot_vision_adapter,
        finalize_screenshot_capture,
        validate_screenshot_capture,
    )

    capture = ScreenshotCaptureResult.model_validate(result)
    validation = validate_screenshot_capture(
        capture,
        item.expected_text,
        rejected_text=item.rejected_text,
        locale=ReportLocale(ctx.deps.report_locale),
        adapter=default_screenshot_vision_adapter(
            project_id=ctx.deps.project_id,
            run_id=ctx.deps.run_id,
            workflow_task_id=ctx.deps.workflow_task_id,
            held_model_concurrency_key=ctx.deps.held_model_concurrency_key,
        ),
    )
    if ctx.deps.run_id:
        usage_finding = record_screenshot_model_usage(
            ScreenshotModelUsageContext(
                project_id=ctx.deps.project_id,
                run_id=ctx.deps.run_id,
                workflow_task_id=ctx.deps.workflow_task_id,
                scenario=capture.scenario,
                url=capture.url,
                image_path=capture.path,
                attempt=validation,
            )
        )
        if usage_finding is not None:
            ctx.deps.evidence.warnings.append(usage_finding.message)
    finalized = finalize_screenshot_capture(capture, [validation])
    replace_evidence_capture(ctx.deps.evidence, finalized)
    return finalized.model_dump(mode="json")


def expected_visible_text(
    expected_text: list[str],
    actions: list[ScreenshotAction],
) -> list[str]:
    accessible_names = {
        action.role_name.strip().casefold()
        for action in actions
        if action.role_name is not None
    }
    return [
        value
        for value in expected_text[:8]
        if value.strip().casefold() not in accessible_names
    ]


def screenshot_attempt_signature(  # noqa: PLR0913 - mirrors model-facing attempt fields
    *,
    change_id: str,
    claim: str,
    route: str,
    expected_text: list[str],
    rejected_text: list[str],
    actions: list[ScreenshotAction],
    theme: str,
    capture_target: str,
    width: int,
    height: int,
) -> str:
    return stable_id(
        "screenshot-attempt",
        change_id,
        claim,
        route,
        normalized_signature_text(expected_text),
        normalized_signature_text(rejected_text),
        "\n".join(action.model_dump_json(exclude_none=True) for action in actions),
        theme,
        capture_target,
        str(width),
        str(height),
    )


def normalized_signature_text(values: list[str]) -> str:
    return "\n".join(value.strip().casefold() for value in values)


def inspect_browser_ui(
    config: BrowserToolConfig,
    route: str,
    *,
    actions: list[dict[str, str]] | None = None,
    width: int,
    height: int,
) -> dict[str, Any]:
    target_url, viewport, error = browser_inspection_preflight(
        config,
        route,
        width=width,
        height=height,
    )
    if error is not None:
        return error
    assert target_url is not None and viewport is not None
    playwright_runner = sync_playwright
    assert playwright_runner is not None
    try:
        with playwright_runner() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser_context, page = new_browser_page(
                browser,
                viewport=viewport.model_dump(),
                target_url=target_url,
                auth_type=config.auth_type,
                auth_secret=config.auth_secret,
            )
            navigate_browser_page(page, target_url, config.timeout_ms)
            ensure_allowed_page_origin(page, origin(target_url))
            for action in actions or []:
                execute_browser_step(
                    page,
                    action,
                    config.timeout_ms,
                    allowed_origin=origin(target_url),
                )
            ensure_allowed_page_origin(page, origin(target_url))
            body = page.locator("body")
            result = {
                "url": page.url,
                "title": page.title(),
                "viewport": viewport.model_dump(),
                "visible_text": bounded_text(
                    redact_snapshot(body.inner_text(timeout=1_000)),
                    6_000,
                ),
                "aria_snapshot": bounded_text(
                    redact_snapshot(read_aria_snapshot(body)),
                    8_000,
                ),
                "policy_audit": browser_policy_audit_from_config(
                    config,
                    "allowed",
                    tool_name="inspect_ui",
                ).model_dump(mode="json"),
            }
            browser_context.close()
            browser.close()
            return result
    except Exception as exc:  # noqa: BLE001 - return structured error to the agent
        return dump_browser_capture(
            browser_capture_failure(
                BrowserCaptureErrorCode.CAPTURE_FAILED,
                f"Browser UI inspection failed: {exc}",
                retryable=True,
                policy_audit=browser_policy_audit_from_config(
                    config,
                    "failed",
                    tool_name="inspect_ui",
                ),
            )
        )


def browser_inspection_preflight(
    config: BrowserToolConfig,
    route: str,
    *,
    width: int,
    height: int,
) -> tuple[str | None, ScreenshotViewport | None, dict[str, Any] | None]:
    audit = browser_policy_audit_from_config(
        config,
        "denied",
        tool_name="inspect_ui",
    )
    if not config.enabled:
        return (
            None,
            None,
            dump_browser_capture(
                browser_capture_failure(
                    BrowserCaptureErrorCode.DISABLED,
                    "Browser inspection tool is disabled.",
                    policy_audit=audit,
                )
            ),
        )
    target_url = allowed_target_url(config.base_url, route)
    if target_url is None:
        return (
            None,
            None,
            dump_browser_capture(
                browser_capture_failure(
                    BrowserCaptureErrorCode.ORIGIN_DENIED,
                    "Browser navigation must stay within the configured interface origin.",
                    policy_audit=audit,
                )
            ),
        )
    if sync_playwright is None:
        return (
            None,
            None,
            dump_browser_capture(
                browser_capture_failure(
                    BrowserCaptureErrorCode.PLAYWRIGHT_UNAVAILABLE,
                    "Playwright is required for bounded same-origin UI inspection.",
                    policy_audit=audit,
                )
            ),
        )
    try:
        viewport = ScreenshotViewport(width=width, height=height)
    except ValueError as exc:
        return (
            None,
            None,
            dump_browser_capture(
                browser_capture_failure(
                    BrowserCaptureErrorCode.INVALID_ACTION,
                    f"Invalid browser viewport: {exc}",
                    policy_audit=audit,
                )
            ),
        )
    return target_url, viewport, None


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
        auth_type=config.auth_type,
        auth_secret=config.auth_secret,
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
            browser_context, page = new_browser_page(
                browser,
                viewport={"width": context.width, "height": context.height},
                target_url=context.target_url,
                auth_type=context.auth_type,
                auth_secret=context.auth_secret,
            )
            if context.plan_item and context.plan_item.theme is not ScreenshotTheme.SYSTEM:
                page.emulate_media(color_scheme=context.plan_item.theme.value)
            events = BrowserCaptureEvents()
            register_browser_capture_events(page, events)
            navigate_browser_page(page, context.target_url, context.timeout_ms)
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
            browser_context.close()
            browser.close()
    except Exception as exc:  # noqa: BLE001 - return tool error to the agent
        return browser_capture_failure(
            BrowserCaptureErrorCode.CAPTURE_FAILED,
            f"Browser screenshot failed: {exc}",
            retryable=True,
            policy_audit=browser_policy_audit(context, decision="failed"),
        )
    return record_screenshot(context, diagnostics)


def new_browser_page(
    browser: Any,
    *,
    viewport: dict[str, int],
    target_url: str,
    auth_type: TaskInterfaceAuthType | None,
    auth_secret: SecretStr | None,
) -> tuple[Any, Any]:
    browser_context = browser.new_context(viewport=viewport)
    if auth_type is TaskInterfaceAuthType.COOKIE:
        cookie_entries = task_interface_cookie_entries(auth_secret, target_url)
        if cookie_entries:
            browser_context.add_cookies(cookie_entries)
    elif auth_type is TaskInterfaceAuthType.LOCAL_STORAGE:
        init_script = task_interface_local_storage_init_script(auth_secret, target_url)
        if init_script:
            browser_context.add_init_script(script=init_script)
    return browser_context, browser_context.new_page()


def task_interface_cookie_entries(
    auth_secret: SecretStr | None,
    target_url: str,
) -> list[dict[str, str]]:
    if auth_secret is None:
        return []
    raw = auth_secret.get_secret_value()
    scoped_origin = origin(target_url)
    entries: dict[str, dict[str, str]] = {}
    for pair in raw.split(";"):
        name, separator, value = pair.strip().partition("=")
        if not separator or not name:
            raise ValueError("Invalid UI authentication cookie value.")
        entries[name] = {
            "name": name,
            "value": value.strip(),
            "url": scoped_origin,
        }
    return list(entries.values())


def task_interface_local_storage_init_script(
    auth_secret: SecretStr | None,
    target_url: str,
) -> str | None:
    if auth_secret is None:
        return None
    entries = json.loads(auth_secret.get_secret_value())
    if not isinstance(entries, dict):
        raise ValueError("Invalid UI localStorage authorization value.")
    configuration = json.dumps(
        {"origin": origin(target_url), "entries": entries},
        separators=(",", ":"),
    )
    return (
        "(() => {"
        f"const configuration = {configuration};"
        "if (window.location.origin === configuration.origin) {"
        "Object.entries(configuration.entries).forEach(([key, value]) => "
        "window.localStorage.setItem(key, value));"
        "}"
        "})();"
    )


def register_browser_capture_events(page: Any, events: BrowserCaptureEvents) -> None:
    page.on(
        "console",
        lambda message: (
            events.console_errors.append(message.text) if message.type == "error" else None
        ),
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
    build_identity_locator = page.locator('meta[name="application-version"], meta[name="build-id"]')
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
