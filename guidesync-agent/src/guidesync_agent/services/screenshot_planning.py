from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

from guidesync_agent.schemas import (
    FileChangeSummary,
    GuideSyncRunRequest,
    ReportLocale,
    ScreenshotAction,
    ScreenshotActionKind,
    ScreenshotLocatorKind,
    ScreenshotPlan,
    ScreenshotPlanItem,
    ScreenshotPolicy,
    ScreenshotTheme,
    ScreenshotViewport,
)
from guidesync_agent.services.stable_ids import stable_id

MAX_SCREENSHOT_SCENARIOS = 4
MOBILE_SCREENSHOT_VIEWPORT = ScreenshotViewport(width=390, height=844)


def build_screenshot_plan(
    request: GuideSyncRunRequest,
    file_summaries: list[FileChangeSummary],
) -> ScreenshotPlan:
    candidates = [summary for summary in file_summaries if summary.needs_screenshot_check]
    if not candidates and (
        request.screenshot_policy is ScreenshotPolicy.REQUIRED or not file_summaries
    ):
        candidates = [fallback_summary(request)]
    mobile_menu_summary = next(
        (summary for summary in candidates if is_mobile_menu_summary(summary)),
        None,
    )
    if mobile_menu_summary is not None:
        return ScreenshotPlan(
            policy=request.screenshot_policy.value,
            allowed_origin=allowed_origin(request.task_interface_url),
            locale=request.report.locale.value,
            items=mobile_menu_plan_items(request, mobile_menu_summary),
        )
    items = scenario_candidates(candidates)[:MAX_SCREENSHOT_SCENARIOS]
    return ScreenshotPlan(
        policy=request.screenshot_policy.value,
        allowed_origin=allowed_origin(request.task_interface_url),
        locale=request.report.locale.value,
        items=[plan_item(request, summary, label) for summary, label in items],
    )


def is_mobile_menu_summary(summary: FileChangeSummary) -> bool:
    text = " ".join(
        [
            summary.path,
            summary.what_changed,
            summary.product_impact,
            *summary.affected_components,
            *summary.affected_workflows,
        ]
    ).casefold()
    return "mobile menu" in text or "mobilemenutoggle" in text


def mobile_menu_plan_items(
    request: GuideSyncRunRequest,
    summary: FileChangeSummary,
) -> list[ScreenshotPlanItem]:
    return [
        mobile_menu_plan_item(request, summary, menu_open=False),
        mobile_menu_plan_item(request, summary, menu_open=True),
    ]


def mobile_menu_plan_item(
    request: GuideSyncRunRequest,
    summary: FileChangeSummary,
    *,
    menu_open: bool,
) -> ScreenshotPlanItem:
    state = "open" if menu_open else "closed"
    menu_label = "Меню" if request.report.locale is ReportLocale.RUSSIAN else "Menu"
    change_id = summary.id
    claim = summary.product_impact or summary.what_changed or "Mobile menu toggle state"
    actions = [
        ScreenshotAction(
            kind=ScreenshotActionKind.WAIT_FOR,
            locator_kind=ScreenshotLocatorKind.ROLE,
            locator="button",
            role_name=menu_label,
        )
    ]
    if menu_open:
        actions.extend(
            [
                ScreenshotAction(
                    kind=ScreenshotActionKind.CLICK,
                    locator_kind=ScreenshotLocatorKind.ROLE,
                    locator="button",
                    role_name=menu_label,
                ),
                ScreenshotAction(
                    kind=ScreenshotActionKind.WAIT,
                    wait_ms=300,
                ),
            ]
        )
    caption, alt_text = mobile_menu_copy(request.report.locale, menu_open)
    return ScreenshotPlanItem(
        id=stable_id("scenario", change_id, requested_route(request.task_interface_url), state),
        change_id=change_id,
        claim_id=stable_id("claim", change_id, claim, state),
        claim=claim,
        route=requested_route(request.task_interface_url),
        actions=actions,
        expected_text=[],
        rejected_text=["404", "not found", "sign in", "log in", "loading"],
        requested_state=f"mobile menu {state}",
        viewport=MOBILE_SCREENSHOT_VIEWPORT,
        theme=ScreenshotTheme.LIGHT,
        capture_target="viewport",
        caption=caption,
        alt_text=alt_text,
        evidence_refs=summary.evidence_refs or [f"file-summary:{summary.id}"],
        retry_intent="Retry after waiting for the mobile menu state to settle.",
    )


def mobile_menu_copy(locale: ReportLocale, menu_open: bool) -> tuple[str, str]:
    if locale is ReportLocale.RUSSIAN:
        if menu_open:
            return (
                "Открытое мобильное меню с кнопкой закрытия",  # noqa: RUF001
                "Мобильное меню открыто; кнопка в шапке показывает значок закрытия.",
            )
        return (
            "Закрытое мобильное меню с кнопкой открытия",  # noqa: RUF001
            "Страница документации на мобильном экране с кнопкой открытия меню в шапке.",  # noqa: RUF001
        )
    if menu_open:
        return (
            "Open mobile menu with the close button",
            "The mobile menu is open and the header button shows a close icon.",
        )
    return (
        "Closed mobile menu with the open button",
        "A documentation page on mobile with the menu button in the header.",
    )


def scenario_candidates(
    summaries: list[FileChangeSummary],
) -> list[tuple[FileChangeSummary, str]]:
    candidates: list[tuple[FileChangeSummary, str]] = []
    for summary in summaries:
        labels = unique_values([*summary.affected_workflows, *summary.affected_components])[:2]
        if not labels:
            labels = [summary.product_impact or summary.what_changed or summary.path]
        candidates.extend((summary, label) for label in labels)
    return candidates


def plan_item(
    request: GuideSyncRunRequest,
    summary: FileChangeSummary,
    label: str,
) -> ScreenshotPlanItem:
    route = requested_route(request.task_interface_url)
    change_id = summary.id
    claim = summary.product_impact or summary.what_changed or label
    claim_id = stable_id("claim", change_id, claim)
    scenario_id = stable_id("scenario", change_id, route, label)
    expected = expected_text(summary, label)
    caption, alt_text = localized_copy(request.report.locale, label, claim)
    return ScreenshotPlanItem(
        id=scenario_id,
        change_id=change_id,
        claim_id=claim_id,
        claim=claim,
        route=route,
        actions=(
            [
                ScreenshotAction(
                    kind=ScreenshotActionKind.WAIT_FOR,
                    locator_kind=ScreenshotLocatorKind.TEXT,
                    locator=expected[0],
                )
            ]
            if expected
            else []
        ),
        expected_text=expected,
        rejected_text=["404", "not found", "sign in", "log in", "loading"],
        requested_state=claim,
        viewport=ScreenshotViewport(),
        theme=ScreenshotTheme.LIGHT,
        capture_target="viewport",
        caption=caption,
        alt_text=alt_text,
        evidence_refs=summary.evidence_refs or [f"file-summary:{summary.id}"],
        retry_intent="Retry with a longer semantic wait or another allowed route alias.",
    )


def fallback_summary(request: GuideSyncRunRequest) -> FileChangeSummary:
    repository = request.repositories[0] if request.repositories else None
    return FileChangeSummary(
        id=stable_id("file-summary", request.run_id, request.goal),
        repository_id=(repository.repository_id if repository else None) or "repository",
        path="ui",
        status="unknown",
        technical_summary=request.goal,
        product_impact=request.goal,
        what_changed=request.goal,
        needs_screenshot_check=True,
        evidence_refs=[f"run-goal:{stable_id('goal', request.goal)}"],
    )


def expected_text(summary: FileChangeSummary, label: str) -> list[str]:
    values = [label, *summary.documentation_keywords, *summary.docs_to_search]
    cleaned = (value.strip().strip(".,:;!?()[]{}") for value in values)
    return unique_values(value for value in cleaned if len(value) >= 3)[:8]


def allowed_origin(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def requested_route(url: str | None) -> str:
    if not url:
        return "/"
    parsed = urlparse(url)
    route = parsed.path or "/"
    if parsed.query:
        route = f"{route}?{parsed.query}"
    if parsed.fragment:
        route = f"{route}#{parsed.fragment}"
    return route


def localized_copy(
    locale: ReportLocale,
    label: str,
    claim: str,
) -> tuple[str, str]:
    if locale is ReportLocale.RUSSIAN:
        return (
            f"Где найти: {label}",
            f"Экран раздела «{label}», где можно найти: {claim}",
        )
    return (
        f"Where to find it: {label}",
        f"The {label} screen showing where to find: {claim}",
    )


def unique_values(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
