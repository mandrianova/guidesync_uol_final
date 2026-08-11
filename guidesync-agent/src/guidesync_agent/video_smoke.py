from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from guidesync_agent.app_logging import configure_logging
from guidesync_agent.schemas import (
    PublicationChange,
    PublicationReport,
    ReportLocale,
    VideoPresentationPlan,
    VideoPresentationSlide,
)
from guidesync_agent.services.video_media import assemble_video
from guidesync_agent.services.video_presentation import validate_presentation_duration
from guidesync_agent.services.video_presentation_artifacts import (
    MANIFEST_ARTIFACT_NAME,
    build_video_manifest,
    write_plan_and_transcript,
)
from guidesync_agent.services.video_rendering import render_video_slides
from guidesync_agent.services.video_tts import generate_tts_segments

logger = logging.getLogger(__name__)


def smoke_report() -> PublicationReport:
    changes = [
        PublicationChange(
            id="change-navigation",
            claim_id="claim-navigation",
            title="Clearer navigation",
            summary="Navigation labels are easier to understand.",
            why_it_matters="People can find common actions with less effort.",
        ),
        PublicationChange(
            id="change-feedback",
            claim_id="claim-feedback",
            title="More useful feedback",
            summary="Actions now provide clearer completion feedback.",
            why_it_matters="People can tell when a task has finished.",
        ),
        PublicationChange(
            id="change-guidance",
            claim_id="claim-guidance",
            title="Updated guidance",
            summary="The user guide reflects the current workflow.",
            why_it_matters="Instructions stay aligned with the interface.",
        ),
    ]
    return PublicationReport(
        locale=ReportLocale.ENGLISH,
        product_name="GuideSync sample",
        title="GuideSync sample release notes",
        summary="This sample validates the complete video presentation pipeline.",
        user_value="Release information is available as text, slides, narration, and video.",
        release_date=date(2026, 8, 11),
        changes=changes,
        call_to_action="Review the release notes for complete details.",
    )


def smoke_plan() -> VideoPresentationPlan:
    slides = [
        VideoPresentationSlide(
            id="slide-01",
            position=1,
            headline="A clearer release overview",
            body="Three concise updates are presented in a stable, accessible format.",
            narration=(
                "This sample release overview validates the complete presentation pipeline, "
                "from controlled slide rendering to local narration and video assembly."
            ),
            change_id="change-navigation",
            claim_id="claim-navigation",
        ),
        VideoPresentationSlide(
            id="slide-02",
            position=2,
            headline="Useful feedback at each step",
            body="Completion feedback helps people understand what happened and what to do next.",
            narration=(
                "Clear completion feedback helps people understand when an action has finished "
                "and what they can do next."
            ),
            change_id="change-feedback",
            claim_id="claim-feedback",
        ),
        VideoPresentationSlide(
            id="slide-03",
            position=3,
            headline="Guidance that matches the product",
            body=(
                "The user guide follows the current workflow without exposing "
                "internal diagnostics."
            ),
            narration=(
                "Updated user guidance follows the current product workflow while keeping "
                "internal verification details out of the public release presentation."
            ),
            change_id="change-guidance",
            claim_id="claim-guidance",
        ),
    ]
    return VideoPresentationPlan(
        run_id="video-smoke",
        prompt_version="deterministic-video-smoke-v1",
        slides=slides,
    )


def run_smoke(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = smoke_report()
    plan = smoke_plan()
    write_plan_and_transcript(plan, output_dir)
    slide_paths = render_video_slides(plan, report, output_dir)
    tts = generate_tts_segments(plan, output_dir)
    validate_presentation_duration(tts)
    probe = assemble_video(slide_paths, tts.segments, output_dir)
    manifest = build_video_manifest(plan.run_id, plan, slide_paths, tts, probe)
    manifest_path = output_dir / MANIFEST_ARTIFACT_NAME
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    logger.info(
        "Video smoke passed: output=%s duration=%.3fs codec=%s/%s sha256=%s",
        output_dir / manifest.video_artifact_name,
        probe.duration_seconds,
        probe.video_codec,
        probe.audio_codec,
        probe.sha256,
    )
    return output_dir / manifest.video_artifact_name


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        description="Run deterministic real-TTS and FFmpeg video presentation smoke."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/app/logs/video-smoke"),
    )
    args = parser.parse_args()
    run_smoke(args.output_dir)


if __name__ == "__main__":
    main()
