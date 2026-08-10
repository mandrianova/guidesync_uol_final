from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from httpx import TimeoutException as HttpxTimeoutException
from openai import APIError as OpenAIAPIError
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior

from guidesync_agent.agent_runtime.concurrency import agent_concurrency_key
from guidesync_agent.agent_runtime.pydantic_ai import (
    PydanticAgentRunRequest,
    run_pydantic_agent,
)
from guidesync_agent.agent_runtime.release_notes_output import (
    documentation_update_from_model_output,
    split_change_evidence_refs,
)
from guidesync_agent.agent_runtime.release_notes_validation import (
    release_notes_candidate_screenshot_available,
    release_notes_evidence_consistency_issue,
    release_notes_output_issue,
    release_notes_screenshot_requirement_satisfied,
)
from guidesync_agent.prompts.release_notes import (
    RELEASE_NOTES_AGENT_INSTRUCTIONS,
    ReleaseNotesPromptInput,
    build_release_notes_task_prompt,
    release_notes_agent_prompt_metadata,
)
from guidesync_agent.schemas import (
    AnalysisArtifactManifest,
    DocumentationEditPlan,
    DocumentationUpdate,
    DocumentationUpdateModelOutput,
    EvidenceBundle,
    ModelRole,
    ProviderConfig,
    ScreenshotPolicy,
)
from guidesync_agent.tools.browser import (
    browser_tool_config_from_provider,
    register_browser_agent_tools,
)
from guidesync_agent.tools.evidence import EvidenceAgentDeps, register_evidence_agent_tools

RELEASE_NOTES_AGENT_RETRIES = 2
RELEASE_NOTES_SEMANTIC_ATTEMPTS = 3
RELEASE_NOTES_PROVIDER_FAILURE_ATTEMPTS = 3
REQUIRED_SCREENSHOT_TOTAL_TIMEOUT_MULTIPLIER = 3
RETRYABLE_RELEASE_NOTES_ERRORS = (
    ModelAPIError,
    UnexpectedModelBehavior,
    OpenAIAPIError,
    HttpxTimeoutException,
)

__all__ = [
    "ReleaseNotesGenerationInput",
    "documentation_update_from_model_output",
    "release_notes_evidence_consistency_issue",
    "run_release_notes_agent",
    "split_change_evidence_refs",
]


@dataclass(frozen=True)
class ReleaseNotesGenerationInput:
    goal: str
    audience: str
    evidence: EvidenceBundle
    analysis_manifest: AnalysisArtifactManifest | None = None
    edit_plan: DocumentationEditPlan | None = None
    product_name: str = "GuideSync"
    locale: str = "en"
    task_interface_url: str | None = None
    screenshot_policy: ScreenshotPolicy = ScreenshotPolicy.DISABLED
    screenshot_candidate_change_ids: list[str] = field(default_factory=list)


async def run_release_notes_agent(
    generation_input: ReleaseNotesGenerationInput,
    config: ProviderConfig,
) -> tuple[DocumentationUpdate, dict[str, Any]]:
    config = release_notes_runtime_config(config, generation_input.screenshot_policy)
    browser = browser_tool_config_from_provider(config)
    if generation_input.screenshot_policy is ScreenshotPolicy.DISABLED or not (
        generation_input.task_interface_url or ""
    ).strip():
        browser = browser.model_copy(update={"enabled": False})
    deps = EvidenceAgentDeps(
        evidence=generation_input.evidence,
        browser=browser,
        analysis_manifest=generation_input.analysis_manifest,
        report_locale=generation_input.locale,
        screenshot_policy=generation_input.screenshot_policy,
        screenshot_candidate_change_ids=generation_input.screenshot_candidate_change_ids,
        project_id=metadata_string(config.metadata, "project_id"),
        run_id=metadata_string(config.metadata, "run_id"),
        workflow_task_id=metadata_string(config.metadata, "workflow_task_id"),
        held_model_concurrency_key=agent_concurrency_key(config),
    )
    output, attempt_usages, prompt = await generate_release_notes_output(
        generation_input,
        config,
        deps,
    )
    usage = combined_release_notes_usage(attempt_usages)
    usage.update(
        {
            "prompt_strategy": "release_notes_agent_tools",
            "prompt_input_chars": len(prompt),
            **release_notes_agent_prompt_metadata(),
            **release_notes_agent_structured_output_aliases(usage),
            "evidence_agent_tool_calls": deps.tool_calls,
            "prompt_evidence_commits_total": len(generation_input.evidence.commits),
            "prompt_evidence_docs_total": len(generation_input.evidence.documentation),
            "prompt_evidence_screenshots_total": len(generation_input.evidence.browser_screenshots),
            "prompt_evidence_warnings_total": len(generation_input.evidence.warnings),
        }
    )
    return documentation_update_from_model_output(output), usage


async def generate_release_notes_output(
    generation_input: ReleaseNotesGenerationInput,
    config: ProviderConfig,
    deps: EvidenceAgentDeps,
) -> tuple[DocumentationUpdateModelOutput, list[dict[str, Any]], str]:
    attempt_usages: list[dict[str, Any]] = []
    correction: str | None = None
    output: DocumentationUpdateModelOutput | None = None
    last_attempt_error: Exception | None = None
    prompt = ""
    semantic_attempts = 0
    provider_failures = 0
    while (
        semantic_attempts < RELEASE_NOTES_SEMANTIC_ATTEMPTS
        and provider_failures < RELEASE_NOTES_PROVIDER_FAILURE_ATTEMPTS
    ):
        browser_tools_enabled = not (
            correction is not None
            and (
                (
                    output is not None
                    and release_notes_screenshot_requirement_satisfied(output, deps)
                )
                or release_notes_candidate_screenshot_available(deps)
            )
        )
        prompt = release_notes_prompt(
            generation_input,
            correction=correction,
            browser_tools_enabled=browser_tools_enabled,
        )
        try:
            runtime_result = await run_pydantic_agent(
                PydanticAgentRunRequest(
                    prompt=prompt,
                    instructions=RELEASE_NOTES_AGENT_INSTRUCTIONS,
                    output_model=DocumentationUpdateModelOutput,
                    deps=deps,
                    deps_type=EvidenceAgentDeps,
                    config=config,
                    model_role=ModelRole.ORCHESTRATOR,
                    project_id=metadata_string(config.metadata, "project_id"),
                    run_id=metadata_string(config.metadata, "run_id"),
                    workflow_task_id=metadata_string(
                        config.metadata, "workflow_task_id"
                    ),
                    prompt_metadata=release_notes_agent_prompt_metadata(),
                    register_tools=(
                        register_release_notes_agent_tools
                        if browser_tools_enabled
                        else register_evidence_agent_tools
                    ),
                    retries=RELEASE_NOTES_AGENT_RETRIES,
                    requires_tools=(
                        generation_input.screenshot_policy is ScreenshotPolicy.REQUIRED
                    ),
                    allow_early_output=True,
                )
            )
        except RETRYABLE_RELEASE_NOTES_ERRORS as exc:
            last_attempt_error = exc
            provider_failures += 1
            correction = record_release_notes_provider_failure(
                attempt_usages,
                exc,
                correction,
            )
            continue
        last_attempt_error = None
        semantic_attempts += 1
        attempt_usages.append(runtime_result.usage)
        output = DocumentationUpdateModelOutput.model_validate(runtime_result.output)
        correction = release_notes_output_issue(output, deps)
        if correction is None:
            break
    if output is None or correction is not None:
        error = RuntimeError(
            "Release-note output remained inconsistent after bounded correction attempts: "
            f"{correction or 'no structured output was returned'}"
        )
        if last_attempt_error is not None:
            raise error from last_attempt_error
        raise error
    return output, attempt_usages, prompt


def record_release_notes_provider_failure(
    attempt_usages: list[dict[str, Any]],
    error: Exception,
    correction: str | None,
) -> str:
    attempt_usages.append(
        {
            "release_notes_agent_attempt_error": str(error),
            "release_notes_agent_attempt_error_type": type(error).__name__,
        }
    )
    return correction or (
        "The previous model attempt ended before returning a valid structured report. "
        "Return a complete structured report from the available evidence."
    )


def release_notes_prompt(
    generation_input: ReleaseNotesGenerationInput,
    *,
    correction: str | None,
    browser_tools_enabled: bool = True,
) -> str:
    prompt = build_release_notes_task_prompt(
        ReleaseNotesPromptInput(
            goal=generation_input.goal,
            audience=generation_input.audience,
            evidence=generation_input.evidence,
            analysis_manifest=generation_input.analysis_manifest,
            edit_plan=generation_input.edit_plan,
            product_name=generation_input.product_name,
            locale=generation_input.locale,
            task_interface_url=generation_input.task_interface_url,
            screenshot_policy=generation_input.screenshot_policy,
            screenshot_candidate_change_ids=generation_input.screenshot_candidate_change_ids,
        )
    )
    if correction is None:
        return prompt
    correction_prompt = (
        f"{prompt}\n\nCorrection required from the previous attempt:\n{correction}\n"
        "Return a complete corrected report. Reuse already approved evidence when it still "
        "supports the corrected change; do not repeat an unchanged failed tool call."
    )
    if browser_tools_enabled:
        return correction_prompt
    return (
        f"{correction_prompt}\nA publication-approved screenshot already satisfies the "
        "required coverage. Browser tools are unavailable for this correction; reuse "
        "that image and correct only the report content."
    )


def combined_release_notes_usage(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    if not attempts:
        return {}
    combined = dict(attempts[-1])
    for key in (
        "requests",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "tool_calls",
    ):
        values = [attempt.get(key) for attempt in attempts]
        if all(isinstance(value, int) for value in values):
            combined[key] = sum(values)
    combined["release_notes_generation_attempts"] = len(attempts)
    provider_failures = sum(
        "release_notes_agent_attempt_error" in attempt for attempt in attempts
    )
    semantic_attempts = len(attempts) - provider_failures
    combined["release_notes_provider_failure_attempts"] = provider_failures
    combined["release_notes_semantic_attempts"] = semantic_attempts
    combined["release_notes_correction_attempts"] = max(0, semantic_attempts - 1)
    combined["release_notes_attempt_transcript_ids"] = [
        transcript_id
        for attempt in attempts
        if isinstance((transcript_id := attempt.get("llm_transcript_id")), str)
    ]
    return combined


def release_notes_runtime_config(
    config: ProviderConfig,
    screenshot_policy: ScreenshotPolicy,
) -> ProviderConfig:
    if screenshot_policy is not ScreenshotPolicy.REQUIRED:
        return config
    limits = config.execution_limits
    required_total = config.timeout_seconds * REQUIRED_SCREENSHOT_TOTAL_TIMEOUT_MULTIPLIER
    if limits.total_timeout_seconds >= required_total:
        return config
    return config.model_copy(
        update={
            "execution_limits": limits.model_copy(
                update={"total_timeout_seconds": required_total}
            )
        }
    )


def register_release_notes_agent_tools(agent: Any) -> None:
    register_evidence_agent_tools(agent)
    register_browser_agent_tools(agent)


def metadata_string(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def release_notes_agent_structured_output_aliases(usage: dict[str, Any]) -> dict[str, Any]:
    aliases: dict[str, Any] = {}
    for suffix in ("mode", "schema", "schema_sha256", "diagnostics"):
        value = usage.get(f"{ModelRole.ORCHESTRATOR.value}_structured_output_{suffix}")
        if value is not None:
            aliases[f"release_notes_agent_structured_output_{suffix}"] = value
    return aliases
