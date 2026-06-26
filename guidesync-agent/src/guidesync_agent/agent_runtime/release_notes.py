from __future__ import annotations

from dataclasses import asdict, is_dataclass
from inspect import isawaitable
from typing import Any, cast

from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings as AgentModelSettings

from guidesync_agent.llm.factory import build_pydantic_ai_model
from guidesync_agent.prompts.release_notes import (
    RELEASE_NOTES_AGENT_INSTRUCTIONS,
    build_release_notes_task_prompt,
    release_notes_agent_prompt_metadata,
)
from guidesync_agent.schemas import DocumentationUpdate, EvidenceBundle, ProviderConfig
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
    model = build_pydantic_ai_model(config)
    agent = cast(
        Agent[EvidenceAgentDeps, DocumentationUpdate],
        Agent(
            model,
            output_type=DocumentationUpdate,
            instructions=RELEASE_NOTES_AGENT_INSTRUCTIONS,
            deps_type=EvidenceAgentDeps,
            model_settings=model_settings_from_provider(config),
            retries=RELEASE_NOTES_AGENT_RETRIES,
        ),
    )
    register_evidence_agent_tools(agent)
    register_browser_agent_tools(agent)
    deps = EvidenceAgentDeps(
        evidence=evidence,
        browser=browser_tool_config_from_provider(config),
    )
    prompt = build_release_notes_task_prompt(goal, audience, evidence)
    try:
        result = await agent.run(prompt, deps=deps)
    finally:
        await close_model_client(model)
    usage = agent_usage(result)
    usage.update(
        {
            "prompt_strategy": "release_notes_agent_tools",
            "prompt_input_chars": len(prompt),
            **release_notes_agent_prompt_metadata(),
            "evidence_agent_tool_calls": deps.tool_calls,
            "prompt_evidence_commits_total": len(evidence.commits),
            "prompt_evidence_docs_total": len(evidence.documentation),
            "prompt_evidence_screenshots_total": len(evidence.browser_screenshots),
            "prompt_evidence_warnings_total": len(evidence.warnings),
        }
    )
    return DocumentationUpdate.model_validate(result.output), usage


async def close_model_client(model: Any) -> None:
    try:
        client = getattr(model, "client", None)
        close = getattr(client, "close", None)
        if not callable(close):
            return
        result = close()
        if isawaitable(result):
            await result
    except Exception:  # noqa: BLE001 - cleanup should not fail a successful model run
        return


def model_settings_from_provider(config: ProviderConfig) -> AgentModelSettings | None:
    if config.thinking is None:
        return None
    return {"thinking": config.thinking}


def agent_usage(result: Any) -> dict[str, Any]:
    if not hasattr(result, "usage"):
        return {}
    try:
        usage = result.usage
        usage_dump = getattr(usage, "model_dump", None)
        if callable(usage_dump):
            return usage_dump()
        if is_dataclass(usage):
            return asdict(usage)
        usage_obj = usage() if callable(usage) else usage
        usage_dump = getattr(usage_obj, "model_dump", None)
        return usage_dump() if callable(usage_dump) else {}
    except Exception:  # noqa: BLE001 - best effort metadata only
        return {}
