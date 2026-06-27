from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from guidesync_agent.schemas import (
    AgentLoopToolDescriptor,
    AgentLoopToolName,
    AgentToolDefinition,
    AgentToolPermission,
    AgentToolRisk,
    AgentToolScope,
    AgentToolSideEffect,
)

DEFAULT_TOOL_REGISTRY_ID = "guidesync-read-only-agent-tools:v1"
READ_ONLY_POLICY_SUMMARY = (
    "Read-only scoped repository, diff, project-profile, knowledge-base, browser, "
    "and validation tools. Writes, shell/process execution, arbitrary external "
    "network access, message sending, repository mutation, database mutation, and "
    "out-of-scope reads are denied."
)


def agent_loop_tool_descriptor(
    name: AgentLoopToolName,
    description: str,
    argument_schema: dict[str, Any] | None = None,
) -> AgentLoopToolDescriptor:
    return AgentLoopToolDescriptor(
        name=name,
        description=description,
        argument_schema=argument_schema or {},
        definition=agent_loop_tool_definition(name),
    )


def agent_loop_tool_definition(name: AgentLoopToolName) -> AgentToolDefinition:
    return LOOP_TOOL_DEFINITIONS[name]


def agent_loop_tool_definitions(
    names: Iterable[AgentLoopToolName],
) -> dict[AgentLoopToolName, AgentToolDefinition]:
    return {name: agent_loop_tool_definition(name) for name in names}


def read_only_tool(
    name: AgentLoopToolName | str,
    *,
    purpose: str,
    scope: AgentToolScope,
    timeout_seconds: float = 10.0,
    max_output_chars: int = 32_000,
    audit_summary: str = "",
) -> AgentToolDefinition:
    return AgentToolDefinition(
        name=name.value if isinstance(name, AgentLoopToolName) else name,
        purpose=purpose,
        scope=scope,
        risk=AgentToolRisk.LOW,
        side_effect=AgentToolSideEffect.READ_ONLY,
        permission=AgentToolPermission.READ_ONLY_ALLOWED,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
        audit_summary=audit_summary or purpose,
    )


LOOP_TOOL_DEFINITIONS: dict[AgentLoopToolName, AgentToolDefinition] = {
    AgentLoopToolName.INSPECT_REPOSITORY_SUMMARY: read_only_tool(
        AgentLoopToolName.INSPECT_REPOSITORY_SUMMARY,
        purpose="Inspect configured repository metadata and cache status for the project.",
        scope=AgentToolScope.PROJECT_PROFILE,
    ),
    AgentLoopToolName.LIST_REPOSITORY_FILES: read_only_tool(
        AgentLoopToolName.LIST_REPOSITORY_FILES,
        purpose="List repository-cache files within the project scope.",
        scope=AgentToolScope.REPOSITORY_CACHE,
    ),
    AgentLoopToolName.READ_REPOSITORY_FILE: read_only_tool(
        AgentLoopToolName.READ_REPOSITORY_FILE,
        purpose="Read a bounded repository-cache file window within the project scope.",
        scope=AgentToolScope.REPOSITORY_CACHE,
        max_output_chars=64_000,
    ),
    AgentLoopToolName.SEARCH_REPOSITORY_FILES: read_only_tool(
        AgentLoopToolName.SEARCH_REPOSITORY_FILES,
        purpose="Search repository-cache files within the project scope.",
        scope=AgentToolScope.REPOSITORY_CACHE,
    ),
    AgentLoopToolName.READ_RAW_DIFF: read_only_tool(
        AgentLoopToolName.READ_RAW_DIFF,
        purpose="Read a bounded raw diff window for a changed file.",
        scope=AgentToolScope.RAW_DIFF,
    ),
    AgentLoopToolName.READ_PROJECT_PROFILE: read_only_tool(
        AgentLoopToolName.READ_PROJECT_PROFILE,
        purpose="Read the latest GuideSync-generated project profile.",
        scope=AgentToolScope.PROJECT_PROFILE,
    ),
    AgentLoopToolName.SEARCH_KNOWLEDGE_BASE: read_only_tool(
        AgentLoopToolName.SEARCH_KNOWLEDGE_BASE,
        purpose="Search project-scoped knowledge-base sections.",
        scope=AgentToolScope.KNOWLEDGE_BASE,
    ),
    AgentLoopToolName.READ_KNOWLEDGE_DOCUMENT: read_only_tool(
        AgentLoopToolName.READ_KNOWLEDGE_DOCUMENT,
        purpose="Read a bounded project knowledge-document window.",
        scope=AgentToolScope.KNOWLEDGE_BASE,
        max_output_chars=64_000,
    ),
}


PYDANTIC_AI_TOOL_DEFINITIONS: dict[str, AgentToolDefinition] = {
    "summarize_evidence": read_only_tool(
        "summarize_evidence",
        purpose="Summarize collected evidence, repositories, commits, docs, and screenshots.",
        scope=AgentToolScope.VALIDATION,
    ),
    "list_repositories": read_only_tool(
        "list_repositories",
        purpose="List evidence repository identifiers.",
        scope=AgentToolScope.REPOSITORY_CACHE,
    ),
    "list_commits": read_only_tool(
        "list_commits",
        purpose="List collected commit evidence.",
        scope=AgentToolScope.RAW_DIFF,
    ),
    "search_commits": read_only_tool(
        "search_commits",
        purpose="Search collected commit and diff evidence.",
        scope=AgentToolScope.RAW_DIFF,
    ),
    "get_commit": read_only_tool(
        "get_commit",
        purpose="Read one collected commit evidence record.",
        scope=AgentToolScope.RAW_DIFF,
    ),
    "list_documentation": read_only_tool(
        "list_documentation",
        purpose="List product documentation evidence excerpts.",
        scope=AgentToolScope.KNOWLEDGE_BASE,
    ),
    "get_documentation": read_only_tool(
        "get_documentation",
        purpose="Read one product documentation evidence excerpt.",
        scope=AgentToolScope.KNOWLEDGE_BASE,
    ),
    "search_documentation": read_only_tool(
        "search_documentation",
        purpose="Search product documentation evidence excerpts.",
        scope=AgentToolScope.KNOWLEDGE_BASE,
    ),
    "list_warnings": read_only_tool(
        "list_warnings",
        purpose="List collection and validation warnings.",
        scope=AgentToolScope.VALIDATION,
    ),
    "inspect_browser_evidence": read_only_tool(
        "inspect_browser_evidence",
        purpose="Inspect browser screenshot and OCR validation evidence.",
        scope=AgentToolScope.BROWSER_READ,
    ),
    "validate_tool_result": read_only_tool(
        "validate_tool_result",
        purpose="Validate model tool-result usage and evidence refs.",
        scope=AgentToolScope.VALIDATION,
    ),
}


def tool_factory_definitions(workflow: str) -> dict[str, AgentToolDefinition]:
    definitions: dict[str, AgentToolDefinition] = {}
    if workflow in {"documentation_update", "project_profile", "model_comparison"}:
        definitions.update(
            {
                "list_changed_files": read_only_tool(
                    "list_changed_files",
                    purpose="List changed files from repository evidence.",
                    scope=AgentToolScope.RAW_DIFF,
                ),
                "read_file_window": read_only_tool(
                    "read_file_window",
                    purpose="Read a bounded repository file window.",
                    scope=AgentToolScope.REPOSITORY_CACHE,
                    max_output_chars=64_000,
                ),
                "read_diff_window": read_only_tool(
                    "read_diff_window",
                    purpose="Read a bounded diff window.",
                    scope=AgentToolScope.RAW_DIFF,
                    max_output_chars=64_000,
                ),
                "search_repository": read_only_tool(
                    "search_repository",
                    purpose="Search repository-cache files.",
                    scope=AgentToolScope.REPOSITORY_CACHE,
                ),
                "search_knowledge_base": read_only_tool(
                    "search_knowledge_base",
                    purpose="Search project-scoped knowledge-base sections.",
                    scope=AgentToolScope.KNOWLEDGE_BASE,
                ),
                "get_knowledge_document_ref": read_only_tool(
                    "get_knowledge_document_ref",
                    purpose="Read knowledge document metadata refs.",
                    scope=AgentToolScope.KNOWLEDGE_BASE,
                ),
                "read_knowledge_document_window": read_only_tool(
                    "read_knowledge_document_window",
                    purpose="Read a bounded knowledge document window.",
                    scope=AgentToolScope.KNOWLEDGE_BASE,
                    max_output_chars=64_000,
                ),
            }
        )
    definitions["validate_tool_result"] = PYDANTIC_AI_TOOL_DEFINITIONS[
        "validate_tool_result"
    ]
    return definitions
