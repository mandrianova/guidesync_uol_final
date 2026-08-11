from __future__ import annotations

from guidesync_agent.agent_runtime.pydantic_ai import (
    PydanticAgentRunRequest,
    run_pydantic_agent,
)
from guidesync_agent.prompts.video_presentation import (
    VIDEO_PRESENTATION_PROMPT_VERSION,
    video_presentation_prompt,
    video_presentation_task_prompt,
)
from guidesync_agent.schemas import (
    ModelRole,
    ProviderConfig,
    PublicationReport,
    VideoPresentationModelOutput,
    VideoPresentationPlan,
    VideoPresentationSlide,
)


async def generate_video_presentation_plan(
    report: PublicationReport,
    config: ProviderConfig,
    *,
    project_id: str,
    run_id: str,
    workflow_task_id: str,
) -> VideoPresentationPlan:
    prompt_file = video_presentation_prompt()
    runtime_result = await run_pydantic_agent(
        PydanticAgentRunRequest(
            prompt=video_presentation_task_prompt(report),
            instructions=prompt_file.content,
            output_model=VideoPresentationModelOutput,
            deps=report,
            deps_type=PublicationReport,
            config=config,
            model_role=ModelRole.ORCHESTRATOR,
            project_id=project_id,
            run_id=run_id,
            workflow_task_id=workflow_task_id,
            prompt_metadata=prompt_file.usage_metadata("video_presentation"),
            retries=1,
            requires_tools=False,
            allow_early_output=True,
        )
    )
    return video_plan_from_model_output(
        run_id,
        report,
        VideoPresentationModelOutput.model_validate(runtime_result.output),
    )


def video_plan_from_model_output(
    run_id: str,
    report: PublicationReport,
    output: VideoPresentationModelOutput,
) -> VideoPresentationPlan:
    changes = {change.id: change for change in report.changes}
    slides = []
    for index, change_id in enumerate(output.change_ids):
        change = changes.get(change_id)
        if change is None:
            raise ValueError(f"Video slide references unknown change_id: {change_id}")
        claim_id = output.claim_ids[index]
        if claim_id != change.claim_id:
            raise ValueError(f"Video slide claim_id {claim_id} does not match change {change_id}.")
        screenshot_name = output.screenshot_artifact_names[index].strip()
        approved_names = {item.artifact_name for item in change.screenshots}
        if screenshot_name and screenshot_name not in approved_names:
            raise ValueError(
                "Video slide screenshot is not publication-approved for its change: "
                f"{screenshot_name}"
            )
        validate_plain_slide_text(
            output.slide_headlines[index],
            output.slide_bodies[index],
            output.slide_narrations[index],
        )
        slides.append(
            VideoPresentationSlide(
                id=f"slide-{index + 1:02d}",
                position=index + 1,
                headline=output.slide_headlines[index].strip(),
                body=output.slide_bodies[index].strip(),
                narration=output.slide_narrations[index].strip(),
                change_id=change_id,
                claim_id=claim_id,
                screenshot_artifact_names=[screenshot_name] if screenshot_name else [],
            )
        )
    return VideoPresentationPlan(
        run_id=run_id,
        prompt_version=VIDEO_PRESENTATION_PROMPT_VERSION,
        slides=slides,
    )


def validate_plain_slide_text(*values: str) -> None:
    for value in values:
        normalized = value.lower()
        if (
            "http://" in normalized
            or "https://" in normalized
            or "javascript:" in normalized
            or ("<" in value and ">" in value)
        ):
            raise ValueError("Video slide content must be plain text without markup or URLs.")
