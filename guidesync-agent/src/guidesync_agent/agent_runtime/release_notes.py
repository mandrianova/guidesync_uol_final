from __future__ import annotations

from typing import Any

from guidesync_agent.prompts.release_notes import (
    RELEASE_NOTES_AGENT_INSTRUCTIONS,
    build_release_notes_task_prompt,
    release_notes_agent_prompt_metadata,
)
from guidesync_agent.schemas import DocumentationUpdate, EvidenceBundle, ModelRole, ProviderConfig
from guidesync_agent.services.pydantic_agent_runtime import run_pydantic_agent
from guidesync_agent.tools.browser import (
    browser_tool_config_from_provider,
    register_browser_agent_tools,
)
from guidesync_agent.tools.evidence import EvidenceAgentDeps, register_evidence_agent_tools

RELEASE_NOTES_AGENT_RETRIES = 3


async def run_release_notes_agent(
    *,
    goal: str,
    audience: str,
    evidence: EvidenceBundle,
    config: ProviderConfig,
) -> tuple[DocumentationUpdate, dict[str, Any]]:
    deps = EvidenceAgentDeps(
        evidence=evidence,
        browser=browser_tool_config_from_provider(config),
    )
    prompt = build_release_notes_task_prompt(goal, audience, evidence)
    runtime_result = await run_pydantic_agent(
        prompt=prompt,
        instructions=RELEASE_NOTES_AGENT_INSTRUCTIONS,
        output_model=DocumentationUpdate,
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
    usage = runtime_result.usage
    usage.update(
        {
            "prompt_strategy": "release_notes_agent_tools",
            "prompt_input_chars": len(prompt),
            **release_notes_agent_prompt_metadata(),
            **release_notes_agent_structured_output_aliases(usage),
            "evidence_agent_tool_calls": deps.tool_calls,
            "prompt_evidence_commits_total": len(evidence.commits),
            "prompt_evidence_docs_total": len(evidence.documentation),
            "prompt_evidence_screenshots_total": len(evidence.browser_screenshots),
            "prompt_evidence_warnings_total": len(evidence.warnings),
        }
    )
    return DocumentationUpdate.model_validate(runtime_result.output), usage


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
