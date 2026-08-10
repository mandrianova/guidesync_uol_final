from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    DocumentationUpdate,
    DocumentationUpdateChange,
    EvidenceBundle,
    GuideSyncRunResult,
    PublicationChange,
    PublicationReport,
    PublicationScreenshotRef,
    ScreenshotValidationStatus,
)
from guidesync_agent.services.stable_ids import stable_id


def build_publication_report(result: GuideSyncRunResult) -> PublicationReport | None:
    update = result.update
    if update is None:
        return None

    screenshots = approved_screenshots(result)
    change_drafts = update.changes or [aggregate_change_draft(update, screenshots)]
    screenshot_assignments = assign_screenshots_to_changes(
        change_drafts,
        screenshots,
        aggregate=not update.changes,
    )
    changes = [
        publication_change(draft, screenshot_assignments[draft.id])
        for draft in change_drafts
    ]
    return PublicationReport(
        locale=result.request.report.locale,
        product_name=result.request.report.product_name,
        title=result.request.report.title,
        summary=update.summary,
        user_value=update.user_facing_change,
        release_date=publication_date(result),
        release_period=release_period(result),
        spotlight_change_id=changes[0].id if changes else None,
        changes=changes,
        call_to_action=call_to_action(),
    )


def aggregate_change_draft(
    update: DocumentationUpdate,
    screenshots: list[BrowserScreenshotEvidence],
) -> DocumentationUpdateChange:
    screenshot = screenshots[0] if screenshots else None
    evidence_refs = unique_values(ref.source for ref in update.evidence_used)
    change_id = (
        screenshot.change_id
        if screenshot is not None and screenshot.change_id
        else stable_id("change", update.title, update.user_facing_change)
    )
    return DocumentationUpdateChange(
        id=change_id,
        title=update.title,
        summary=update.summary,
        user_facing_change=update.user_facing_change,
        how_to_markdown=update.proposed_update_markdown,
        evidence_refs=evidence_refs,
    )


def assign_screenshots_to_changes(
    changes: list[DocumentationUpdateChange],
    screenshots: list[BrowserScreenshotEvidence],
    *,
    aggregate: bool,
) -> dict[str, list[BrowserScreenshotEvidence]]:
    assignments = {change.id: [] for change in changes}
    if aggregate and changes:
        assignments[changes[0].id] = screenshots
        return assignments

    remaining = screenshots.copy()
    for change in changes:
        matched = [item for item in remaining if item.change_id == change.id]
        assignments[change.id].extend(matched)
        remaining = [item for item in remaining if item not in matched]
    for change in changes:
        evidence_refs = set(change.evidence_refs)
        matched = [
            item
            for item in remaining
            if evidence_refs.intersection(screenshot_evidence_refs(item))
        ]
        assignments[change.id].extend(matched)
        remaining = [item for item in remaining if item not in matched]
    return assignments


def has_publishable_screenshot_for_changes(
    evidence: EvidenceBundle,
    changes: Iterable[tuple[str, Iterable[str]]],
) -> bool:
    screenshots = [
        screenshot
        for screenshot in evidence.browser_screenshots
        if screenshot.publication_approved
        and screenshot.prepared_artifact_name
        and screenshot.validation_status is ScreenshotValidationStatus.PASSED
    ]
    change_entries = [(change_id, list(refs)) for change_id, refs in changes]
    if not change_entries:
        return False
    return any(
        screenshot_matches_change(screenshot, change_id, evidence_refs)
        for screenshot in screenshots
        for change_id, evidence_refs in change_entries
    )


def screenshot_matches_change(
    screenshot: BrowserScreenshotEvidence,
    change_id: str,
    evidence_refs: Iterable[str],
) -> bool:
    return screenshot.change_id == change_id or bool(
        set(evidence_refs).intersection(screenshot_evidence_refs(screenshot))
    )


def screenshot_evidence_refs(screenshot: BrowserScreenshotEvidence) -> set[str]:
    if screenshot.plan_item is None:
        return set()
    return set(screenshot.plan_item.evidence_refs)


def publication_change(
    change: DocumentationUpdateChange,
    screenshots: list[BrowserScreenshotEvidence],
) -> PublicationChange:
    screenshot = screenshots[0] if screenshots else None
    claim_id = (
        screenshot.claim_id
        if screenshot is not None and screenshot.claim_id
        else stable_id("claim", change.id, change.user_facing_change, *change.evidence_refs)
    )
    return PublicationChange(
        id=change.id,
        claim_id=claim_id,
        title=change.title,
        summary=change.summary,
        why_it_matters=change.user_facing_change,
        how_to_markdown=change.how_to_markdown,
        evidence_refs=change.evidence_refs,
        screenshots=[publication_screenshot_ref(item) for item in screenshots],
    )


def approved_screenshots(result: GuideSyncRunResult) -> list[BrowserScreenshotEvidence]:
    return [
        screenshot
        for screenshot in result.evidence.browser_screenshots
        if screenshot.publication_approved
        and screenshot.prepared_artifact_name
        and screenshot.validation_status is ScreenshotValidationStatus.PASSED
    ]


def publication_screenshot_ref(
    screenshot: BrowserScreenshotEvidence,
) -> PublicationScreenshotRef:
    if not screenshot.prepared_artifact_name:
        raise ValueError("Publication screenshots require a prepared artifact name.")
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


def call_to_action() -> str:
    return "Open the product and try the updated workflow."


def unique_values(values: Iterable[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
