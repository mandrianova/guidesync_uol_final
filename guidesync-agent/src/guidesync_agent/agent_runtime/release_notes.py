from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from guidesync_agent.llm.factory import build_pydantic_ai_model
from guidesync_agent.prompts.release_notes import (
    RELEASE_NOTES_AGENT_INSTRUCTIONS,
    build_release_notes_task_prompt,
)
from guidesync_agent.schemas import DocumentationUpdate, EvidenceBundle, ProviderConfig
from guidesync_agent.tools.browser import (
    browser_tool_config_from_provider,
    register_browser_agent_tools,
)
from guidesync_agent.tools.evidence import EvidenceAgentDeps, register_evidence_agent_tools


async def run_release_notes_agent(
    *,
    goal: str,
    audience: str,
    evidence: EvidenceBundle,
    config: ProviderConfig,
) -> tuple[DocumentationUpdate, dict[str, Any]]:
    model = build_pydantic_ai_model(config)
    agent = Agent(
        model,
        output_type=DocumentationUpdate,
        instructions=RELEASE_NOTES_AGENT_INSTRUCTIONS,
        deps_type=EvidenceAgentDeps,
    )
    register_evidence_agent_tools(agent)
    register_browser_agent_tools(agent)
    deps = EvidenceAgentDeps(
        evidence=evidence,
        browser=browser_tool_config_from_provider(config),
    )
    prompt = build_release_notes_task_prompt(goal, audience, evidence)
    result = await agent.run(prompt, deps=deps)
    usage = agent_usage(result)
    usage.update(
        {
            "prompt_strategy": "release_notes_agent_tools",
            "prompt_input_chars": len(prompt),
            "evidence_agent_tool_calls": deps.tool_calls,
            "prompt_evidence_commits_total": len(evidence.commits),
            "prompt_evidence_docs_total": len(evidence.documentation),
            "prompt_evidence_screenshots_total": len(evidence.browser_screenshots),
            "prompt_evidence_warnings_total": len(evidence.warnings),
        }
    )
    return DocumentationUpdate.model_validate(result.output), usage


def agent_usage(result: Any) -> dict[str, Any]:
    if not hasattr(result, "usage"):
        return {}
    try:
        usage = result.usage
        usage_obj = usage() if callable(usage) else usage
        usage_dump = getattr(usage_obj, "model_dump", None)
        return usage_dump() if callable(usage_dump) else {}
    except Exception:  # noqa: BLE001 - best effort metadata only
        return {}
