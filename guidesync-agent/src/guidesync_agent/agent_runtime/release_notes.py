from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from httpx import TransportError as HttpxTransportError
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
from guidesync_agent.tools.evidence import (
    EvidenceAgentDeps,
    register_evidence_agent_tools,
    register_evidence_agent_tools_without_knowledge,
)
from guidesync_agent.tools.knowledge_evidence import (
    SelectedKnowledgeEvidence,
    knowledge_manifest_item,
)

RELEASE_NOTES_AGENT_RETRIES = 2
RELEASE_NOTES_SEMANTIC_ATTEMPTS = 2
RELEASE_NOTES_PROVIDER_FAILURE_ATTEMPTS = 2
RETRYABLE_RELEASE_NOTES_ERRORS = (
    ModelAPIError,
    UnexpectedModelBehavior,
    OpenAIAPIError,
    HttpxTransportError,
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
    selected_knowledge: list[SelectedKnowledgeEvidence] = field(default_factory=list)
    knowledge_context_enabled: bool = True


async def run_release_notes_agent(
    generation_input: ReleaseNotesGenerationInput,
    config: ProviderConfig,
) -> tuple[DocumentationUpdate, dict[str, Any]]:
    browser = browser_tool_config_from_provider(config)
    if generation_input.screenshot_policy is ScreenshotPolicy.DISABLED or not (
        generation_input.task_interface_url or ""
    ).strip():
        browser = browser.model_copy(update={"enabled": False})
    deps = EvidenceAgentDeps(
        evidence=generation_input.evidence,
        selected_knowledge=(
            generation_input.selected_knowledge
            if generation_input.knowledge_context_enabled
            else []
        ),
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
    usage = release_notes_usage(generation_input, deps, attempt_usages, prompt)
    return documentation_update_from_model_output(output), usage


def release_notes_usage(
    generation_input: ReleaseNotesGenerationInput,
    deps: EvidenceAgentDeps,
    attempt_usages: list[dict[str, Any]],
    prompt: str,
) -> dict[str, Any]:
    usage = combined_release_notes_usage(attempt_usages)
    usage.update(
        {
            "prompt_strategy": "release_notes_agent_tools",
            "prompt_input_chars": len(prompt),
            **release_notes_agent_prompt_metadata(),
            **release_notes_agent_structured_output_aliases(usage),
            "evidence_agent_tool_calls": deps.tool_calls,
            "knowledge_context_enabled": generation_input.knowledge_context_enabled,
            "knowledge_context_selected": [
                knowledge_manifest_item(item) for item in deps.selected_knowledge
            ],
            "knowledge_context_access_events": deps.knowledge_access_events,
            "knowledge_context_read_refs": sorted(deps.knowledge_read_refs),
            "prompt_evidence_commits_total": len(generation_input.evidence.commits),
            "prompt_evidence_docs_total": len(generation_input.evidence.documentation),
            "prompt_evidence_screenshots_total": len(generation_input.evidence.browser_screenshots),
            "prompt_evidence_warnings_total": len(generation_input.evidence.warnings),
        }
    )
    return usage


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
        prompt, browser_tools_enabled = prepare_release_notes_attempt(
            generation_input,
            deps,
            correction,
            output,
            len(attempt_usages) + 1,
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
                    register_tools=release_notes_tool_registrar(
                        browser_tools_enabled=browser_tools_enabled,
                        knowledge_context_enabled=generation_input.knowledge_context_enabled,
                    ),
                    retries=RELEASE_NOTES_AGENT_RETRIES,
                    requires_tools=release_notes_tool_output_required(generation_input),
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
                prompt_chars=len(prompt),
            )
            continue
        last_attempt_error = None
        semantic_attempts += 1
        attempt_usages.append(
            {**runtime_result.usage, "release_notes_prompt_chars": len(prompt)}
        )
        output = DocumentationUpdateModelOutput.model_validate(runtime_result.output)
        output = normalize_release_notes_change_ids(
            output,
            generation_input.analysis_manifest,
        )
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


def prepare_release_notes_attempt(
    generation_input: ReleaseNotesGenerationInput,
    deps: EvidenceAgentDeps,
    correction: str | None,
    output: DocumentationUpdateModelOutput | None,
    attempt_number: int,
) -> tuple[str, bool]:
    browser_tools_enabled = deps.browser.enabled and not (
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
        previous_output=output,
        browser_tools_enabled=browser_tools_enabled,
    )
    deps.knowledge_attempt = attempt_number
    deps.knowledge_read_refs.clear()
    return prompt, browser_tools_enabled


def normalize_release_notes_change_ids(
    output: DocumentationUpdateModelOutput,
    manifest: AnalysisArtifactManifest | None,
) -> DocumentationUpdateModelOutput:
    if manifest is None or not output.change_ids:
        return output
    canonical_ids = {artifact.id for artifact in manifest.artifacts}
    normalized = [canonical_change_id(value, canonical_ids) for value in output.change_ids]
    if normalized == output.change_ids:
        return output
    return output.model_copy(update={"change_ids": normalized})


def canonical_change_id(value: str, canonical_ids: set[str]) -> str:
    if value in canonical_ids:
        return value
    suffix_matches = [
        candidate
        for candidate in canonical_ids
        if candidate.endswith(f"-{value}")
    ]
    return suffix_matches[0] if len(suffix_matches) == 1 else value


def record_release_notes_provider_failure(
    attempt_usages: list[dict[str, Any]],
    error: Exception,
    correction: str | None,
    *,
    prompt_chars: int,
) -> str:
    attempt_usages.append(
        {
            "release_notes_agent_attempt_error": str(error),
            "release_notes_agent_attempt_error_type": type(error).__name__,
            "release_notes_prompt_chars": prompt_chars,
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
    previous_output: DocumentationUpdateModelOutput | None = None,
    browser_tools_enabled: bool = True,
) -> str:
    if correction is None:
        return initial_release_notes_prompt(generation_input)
    previous_draft = (
        previous_output.model_dump_json()
        if previous_output is not None
        else "No structured draft was returned."
    )
    correction_context = (
        semantic_correction_context(generation_input)
        if previous_output is not None
        else initial_release_notes_prompt(generation_input)
    )
    correction_prompt = (
        f"{correction_context}\n\nPrevious structured draft:\n{previous_draft}\n"
        f"Correction required from the previous attempt:\n{correction}\n"
        "Return the complete corrected report by editing the previous draft. Preserve fields "
        "that are already supported, reuse approved evidence, and do not repeat an unchanged "
        "failed tool call."
    )
    if browser_tools_enabled:
        return correction_prompt
    return (
        f"{correction_prompt}\nBrowser tools are unavailable for this correction. "
        "Keep screenshot use consistent with the configured policy and existing "
        "evidence, and correct only the report content."
    )


def initial_release_notes_prompt(generation_input: ReleaseNotesGenerationInput) -> str:
    return build_release_notes_task_prompt(
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
            knowledge_context_count=(
                len(generation_input.selected_knowledge)
                if generation_input.knowledge_context_enabled
                else 0
            ),
            knowledge_context_enabled=generation_input.knowledge_context_enabled,
        )
    )


def semantic_correction_context(
    generation_input: ReleaseNotesGenerationInput,
) -> str:
    lines = [
        "Revise the existing structured release report without repeating the full analysis.",
        f"Goal: {generation_input.goal}",
        f"Audience: {generation_input.audience}",
        f"Product name: {generation_input.product_name}",
        f"Report locale: {generation_input.locale}",
        f"Screenshot policy: {generation_input.screenshot_policy.value}",
    ]
    if generation_input.task_interface_url:
        lines.append(f"Task interface URL: {generation_input.task_interface_url}")
    if generation_input.screenshot_candidate_change_ids:
        lines.append(
            "Screenshot candidate change IDs: "
            + ", ".join(generation_input.screenshot_candidate_change_ids)
        )
    if generation_input.analysis_manifest is not None:
        lines.append(
            "Allowed change IDs: "
            + ", ".join(
                artifact.id for artifact in generation_input.analysis_manifest.artifacts
            )
        )
    return "\n".join(lines)


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
    prompt_chars = [
        value
        for attempt in attempts
        if isinstance((value := attempt.get("release_notes_prompt_chars")), int)
    ]
    combined["release_notes_attempt_prompt_chars"] = prompt_chars
    combined["release_notes_total_prompt_chars"] = sum(prompt_chars)
    return combined


def release_notes_tool_output_required(
    generation_input: ReleaseNotesGenerationInput,
) -> bool:
    return (
        generation_input.screenshot_policy is ScreenshotPolicy.REQUIRED
        or generation_input.evidence.project_profile is not None
        or bool(
            generation_input.selected_knowledge
            if generation_input.knowledge_context_enabled
            else []
        )
    )


def register_release_notes_agent_tools(agent: Any) -> None:
    register_evidence_agent_tools(agent)
    register_browser_agent_tools(agent)


def register_release_notes_agent_tools_without_knowledge(agent: Any) -> None:
    register_evidence_agent_tools_without_knowledge(agent)
    register_browser_agent_tools(agent)


def release_notes_tool_registrar(
    *,
    browser_tools_enabled: bool,
    knowledge_context_enabled: bool,
) -> Any:
    if browser_tools_enabled:
        return (
            register_release_notes_agent_tools
            if knowledge_context_enabled
            else register_release_notes_agent_tools_without_knowledge
        )
    return (
        register_evidence_agent_tools
        if knowledge_context_enabled
        else register_evidence_agent_tools_without_knowledge
    )


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
