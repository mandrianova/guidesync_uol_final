from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    GuideSyncRunResult,
    PublicationChange,
    PublicationReport,
    PublicationScreenshotRef,
    ReportLocale,
)
from guidesync_agent.services.stable_ids import stable_id


def build_publication_report(result: GuideSyncRunResult) -> PublicationReport | None:
    update = result.update
    if update is None:
        return None

    evidence_refs = unique_values(ref.source for ref in update.evidence_used)
    screenshot = approved_screenshot(result)
    change_id = (
        screenshot.change_id
        if screenshot is not None and screenshot.change_id
        else stable_id("change", update.title, update.user_facing_change)
    )
    claim_id = (
        screenshot.claim_id
        if screenshot is not None and screenshot.claim_id
        else stable_id("claim", update.user_facing_change, *evidence_refs)
    )
    change = PublicationChange(
        id=change_id,
        claim_id=claim_id,
        title=update.title,
        summary=update.summary,
        why_it_matters=update.user_facing_change,
        how_to_markdown=update.proposed_update_markdown,
        evidence_refs=evidence_refs,
        screenshot=publication_screenshot_ref(screenshot),
    )
    locale = result.request.report.locale
    return PublicationReport(
        locale=locale,
        product_name=result.request.report.product_name,
        title=result.request.report.title,
        summary=update.summary,
        user_value=update.user_facing_change,
        release_date=publication_date(result),
        release_period=release_period(result),
        spotlight_change_id=change.id,
        changes=[change],
        call_to_action=call_to_action(locale),
    )


def approved_screenshot(result: GuideSyncRunResult) -> BrowserScreenshotEvidence | None:
    return next(
        (
            screenshot
            for screenshot in result.evidence.browser_screenshots
            if screenshot.publication_approved and screenshot.prepared_artifact_name
        ),
        None,
    )


def publication_screenshot_ref(
    screenshot: BrowserScreenshotEvidence | None,
) -> PublicationScreenshotRef | None:
    if screenshot is None or not screenshot.prepared_artifact_name:
        return None
    return PublicationScreenshotRef(
        artifact_name=screenshot.prepared_artifact_name,
        scenario_id=screenshot.scenario_id or screenshot.scenario,
        caption=screenshot.caption,
        alt_text=screenshot.alt_text,
        width=screenshot.image_width,
        height=screenshot.image_height,
    )


def publication_date(result: GuideSyncRunResult) -> date:
    if result.provider_metadata is not None:
        return result.provider_metadata.completed_at.date()
    return result.evidence.collected_at.date()


def release_period(result: GuideSyncRunResult) -> str | None:
    starts = unique_values(
        repository.since for repository in result.request.repositories if repository.since
    )
    ends = unique_values(
        repository.until for repository in result.request.repositories if repository.until
    )
    if not starts and not ends:
        return None
    start = starts[0] if len(starts) == 1 else min(starts)
    end = ends[0] if len(ends) == 1 else (max(ends) if ends else "present")
    return f"{start} — {end}" if start else f"Through {end}"


def call_to_action(locale: ReportLocale) -> str:
    if locale is ReportLocale.RUSSIAN:
        return "Откройте продукт и попробуйте обновлённый сценарий."
    return "Open the product and try the updated workflow."


def unique_values(values: Iterable[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
