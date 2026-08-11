from __future__ import annotations

import json

from guidesync_agent.prompts.loader import PromptFile, load_prompt_file
from guidesync_agent.schemas import PublicationReport

VIDEO_PRESENTATION_PROMPT_VERSION = "video-presentation-v1"


def video_presentation_prompt() -> PromptFile:
    return load_prompt_file(
        "video_presentation/agent_instructions.md",
        version=VIDEO_PRESENTATION_PROMPT_VERSION,
    )


def video_presentation_task_prompt(report: PublicationReport) -> str:
    facts = {
        "product_name": report.product_name,
        "release_date": report.release_date.isoformat(),
        "release_period": report.release_period,
        "summary": report.summary,
        "user_value": report.user_value,
        "changes": [
            {
                "change_id": change.id,
                "claim_id": change.claim_id,
                "title": change.title,
                "summary": change.summary,
                "why_it_matters": change.why_it_matters,
                "how_to_markdown": change.how_to_markdown,
                "screenshot_artifact_names": [
                    screenshot.artifact_name for screenshot in change.screenshots
                ],
            }
            for change in report.changes
        ],
    }
    return (
        "Create a release-notes video plan from this persisted publication report. "
        "Return all six parallel slide fields with identical lengths. Use an empty string "
        "when a slide should not show a screenshot.\n\n"
        + json.dumps(facts, ensure_ascii=False, indent=2)
    )
