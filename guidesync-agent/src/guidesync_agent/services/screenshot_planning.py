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


def build_screenshot_plan(
    request: GuideSyncRunRequest,
    file_summaries: list[FileChangeSummary],
) -> ScreenshotPlan:
    candidates = [summary for summary in file_summaries if summary.needs_screenshot_check]
    if not candidates and (
        request.screenshot_policy is ScreenshotPolicy.REQUIRED or not file_summaries
    ):
        candidates = [fallback_summary(request)]
    items = scenario_candidates(candidates)[:MAX_SCREENSHOT_SCENARIOS]
    return ScreenshotPlan(
        policy=request.screenshot_policy.value,
        allowed_origin=allowed_origin(request.task_interface_url),
        locale=request.report.locale.value,
        items=[plan_item(request, summary, label) for summary, label in items],
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
    change_id = stable_id("change", summary.repository_id, summary.path, summary.product_impact)
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
        capture_target="role=main",
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
            f"Обновлённый сценарий: {label}",
            f"Интерфейс, подтверждающий изменение: {claim}",
        )
    return (
        f"Updated workflow: {label}",
        f"Interface evidence for the change: {claim}",
    )


def unique_values(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
