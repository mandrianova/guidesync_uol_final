from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from guidesync_agent.agent_runtime.pydantic_ai import (
    PydanticAgentRunRequest,
    run_pydantic_agent,
)
from guidesync_agent.prompts.release_notes import (
    RELEASE_NOTES_AGENT_INSTRUCTIONS,
    build_release_notes_task_prompt,
    release_notes_agent_prompt_metadata,
)
from guidesync_agent.schemas import (
    AnalysisArtifactManifest,
    DocumentationEditPlan,
    DocumentationUpdate,
    DocumentationUpdateModelOutput,
    EvidenceBundle,
    EvidenceReference,
    ModelRole,
    ProviderConfig,
    ReviewerCheck,
)
from guidesync_agent.tools.browser import (
    browser_tool_config_from_provider,
    register_browser_agent_tools,
)
from guidesync_agent.tools.evidence import EvidenceAgentDeps, register_evidence_agent_tools

RELEASE_NOTES_AGENT_RETRIES = 3


@dataclass(frozen=True)
class ReleaseNotesGenerationInput:
    goal: str
    audience: str
    evidence: EvidenceBundle
    analysis_manifest: AnalysisArtifactManifest | None = None
    edit_plan: DocumentationEditPlan | None = None


async def run_release_notes_agent(
    generation_input: ReleaseNotesGenerationInput,
    config: ProviderConfig,
) -> tuple[DocumentationUpdate, dict[str, Any]]:
    deps = EvidenceAgentDeps(
        evidence=generation_input.evidence,
        browser=browser_tool_config_from_provider(config),
        analysis_manifest=generation_input.analysis_manifest,
    )
    prompt = build_release_notes_task_prompt(
        generation_input.goal,
        generation_input.audience,
        generation_input.evidence,
        generation_input.analysis_manifest,
        generation_input.edit_plan,
    )
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
            workflow_task_id=metadata_string(config.metadata, "workflow_task_id"),
            prompt_metadata=release_notes_agent_prompt_metadata(),
            register_tools=register_release_notes_agent_tools,
            retries=RELEASE_NOTES_AGENT_RETRIES,
        )
    )
    usage = runtime_result.usage
    usage.update(
        {
            "prompt_strategy": "release_notes_agent_tools",
            "prompt_input_chars": len(prompt),
            **release_notes_agent_prompt_metadata(),
            **release_notes_agent_structured_output_aliases(usage),
            "evidence_agent_tool_calls": deps.tool_calls,
            "prompt_evidence_commits_total": len(generation_input.evidence.commits),
            "prompt_evidence_docs_total": len(generation_input.evidence.documentation),
            "prompt_evidence_screenshots_total": len(
                generation_input.evidence.browser_screenshots
            ),
            "prompt_evidence_warnings_total": len(generation_input.evidence.warnings),
        }
    )
    return documentation_update_from_model_output(runtime_result.output), usage


def register_release_notes_agent_tools(agent: Any) -> None:
    register_evidence_agent_tools(agent)
    register_browser_agent_tools(agent)


def documentation_update_from_model_output(output: object) -> DocumentationUpdate:
    if isinstance(output, DocumentationUpdate):
        return output
    model_output = DocumentationUpdateModelOutput.model_validate(output)
    evidence_refs = [
        EvidenceReference(
            source=source,
            detail="Cited by the release-notes model output.",
            relevance="Model-selected evidence reference.",
        )
        for source in model_output.evidence_refs
    ]
    reviewer_notes = model_output.reviewer_notes.strip()
    reviewer_checks = [
        ReviewerCheck(
            name="Evidence coverage",
            status="pass" if evidence_refs else "warning",
            notes=(
                "The model cited evidence references."
                if evidence_refs
                else "The model did not cite evidence references."
            ),
        ),
        ReviewerCheck(
            name="Human review",
            status="required",
            notes=reviewer_notes or "Review user impact, terminology, and tone.",
        ),
    ]
    return DocumentationUpdate(
        title=model_output.title,
        summary=model_output.summary,
        user_facing_change=model_output.user_facing_change,
        proposed_update_markdown=model_output.proposed_update_markdown,
        evidence_used=evidence_refs,
        reviewer_checks=reviewer_checks,
        risks_or_limitations=model_output.risks_or_limitations,
        suggested_improvements=model_output.suggested_improvements,
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
