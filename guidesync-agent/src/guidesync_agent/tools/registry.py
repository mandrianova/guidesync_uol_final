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
    "Read-only scoped repository filesystem, diff, project-profile, knowledge-base, "
    "browser, and validation tools. Writes, shell/process execution, arbitrary "
    "external network access, message sending, repository mutation, database "
    "mutation, and out-of-scope reads are denied."
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


def read_only_tool(  # noqa: PLR0913 - declarative tool definition builder
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
    AgentLoopToolName.LIST_ALLOWED_DIRECTORIES: read_only_tool(
        AgentLoopToolName.LIST_ALLOWED_DIRECTORIES,
        purpose="List virtual repository filesystem roots available to this agent.",
        scope=AgentToolScope.REPOSITORY_CACHE,
    ),
    AgentLoopToolName.LIST_DIRECTORY: read_only_tool(
        AgentLoopToolName.LIST_DIRECTORY,
        purpose="List direct children of a virtual repository directory.",
        scope=AgentToolScope.REPOSITORY_CACHE,
    ),
    AgentLoopToolName.LIST_DIRECTORY_WITH_SIZES: read_only_tool(
        AgentLoopToolName.LIST_DIRECTORY_WITH_SIZES,
        purpose="List direct children of a virtual repository directory with sizes.",
        scope=AgentToolScope.REPOSITORY_CACHE,
    ),
    AgentLoopToolName.DIRECTORY_TREE: read_only_tool(
        AgentLoopToolName.DIRECTORY_TREE,
        purpose="Read a recursive virtual repository directory tree as formatted JSON text.",
        scope=AgentToolScope.REPOSITORY_CACHE,
        max_output_chars=64_000,
    ),
    AgentLoopToolName.SEARCH_FILES: read_only_tool(
        AgentLoopToolName.SEARCH_FILES,
        purpose=(
            "Grep-like search for literal text inside virtual repository files, "
            "returning path:line previews."
        ),
        scope=AgentToolScope.REPOSITORY_CACHE,
    ),
    AgentLoopToolName.READ_TEXT_FILE: read_only_tool(
        AgentLoopToolName.READ_TEXT_FILE,
        purpose="Read text from one virtual repository file, optionally by head or tail lines.",
        scope=AgentToolScope.REPOSITORY_CACHE,
        max_output_chars=72_000,
    ),
    AgentLoopToolName.READ_MULTIPLE_FILES: read_only_tool(
        AgentLoopToolName.READ_MULTIPLE_FILES,
        purpose="Read several virtual repository text files with per-file failures inline.",
        scope=AgentToolScope.REPOSITORY_CACHE,
        max_output_chars=100_000,
    ),
    AgentLoopToolName.GET_FILE_INFO: read_only_tool(
        AgentLoopToolName.GET_FILE_INFO,
        purpose="Read metadata for a virtual repository path.",
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
    "list_allowed_directories": read_only_tool(
        "list_allowed_directories",
        purpose="List virtual repository filesystem roots available to this agent.",
        scope=AgentToolScope.REPOSITORY_CACHE,
    ),
    "list_directory": read_only_tool(
        "list_directory",
        purpose="List direct children of a virtual repository directory.",
        scope=AgentToolScope.REPOSITORY_CACHE,
    ),
    "list_directory_with_sizes": read_only_tool(
        "list_directory_with_sizes",
        purpose="List direct children of a virtual repository directory with sizes.",
        scope=AgentToolScope.REPOSITORY_CACHE,
    ),
    "directory_tree": read_only_tool(
        "directory_tree",
        purpose="Read a recursive virtual repository directory tree as formatted JSON text.",
        scope=AgentToolScope.REPOSITORY_CACHE,
        max_output_chars=64_000,
    ),
    "search_files": read_only_tool(
        "search_files",
        purpose=(
            "Grep-like search for literal text inside virtual repository files, "
            "returning path:line previews."
        ),
        scope=AgentToolScope.REPOSITORY_CACHE,
    ),
    "read_text_file": read_only_tool(
        "read_text_file",
        purpose="Read text from one virtual repository file, optionally by head or tail lines.",
        scope=AgentToolScope.REPOSITORY_CACHE,
        max_output_chars=72_000,
    ),
    "read_multiple_files": read_only_tool(
        "read_multiple_files",
        purpose="Read several virtual repository text files with per-file failures inline.",
        scope=AgentToolScope.REPOSITORY_CACHE,
        max_output_chars=100_000,
    ),
    "get_file_info": read_only_tool(
        "get_file_info",
        purpose="Read metadata for a virtual repository path.",
        scope=AgentToolScope.REPOSITORY_CACHE,
    ),
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
    "capture_ui_screenshot": read_only_tool(
        "capture_ui_screenshot",
        purpose=(
            "Capture bounded visual evidence from the configured public no-auth interface origin."
        ),
        scope=AgentToolScope.BROWSER_READ,
        timeout_seconds=30.0,
        max_output_chars=16_000,
        audit_summary="Capture one origin-scoped UI evidence scenario.",
    ).model_copy(update={"retry_policy": "At most two persisted attempts per scenario."}),
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
                "list_allowed_directories": PYDANTIC_AI_TOOL_DEFINITIONS[
                    "list_allowed_directories"
                ],
                "list_directory": PYDANTIC_AI_TOOL_DEFINITIONS["list_directory"],
                "list_directory_with_sizes": PYDANTIC_AI_TOOL_DEFINITIONS[
                    "list_directory_with_sizes"
                ],
                "directory_tree": PYDANTIC_AI_TOOL_DEFINITIONS["directory_tree"],
                "search_files": PYDANTIC_AI_TOOL_DEFINITIONS["search_files"],
                "read_text_file": PYDANTIC_AI_TOOL_DEFINITIONS["read_text_file"],
                "read_multiple_files": PYDANTIC_AI_TOOL_DEFINITIONS[
                    "read_multiple_files"
                ],
                "get_file_info": PYDANTIC_AI_TOOL_DEFINITIONS["get_file_info"],
                "list_changed_files": read_only_tool(
                    "list_changed_files",
                    purpose="List changed files from repository evidence.",
                    scope=AgentToolScope.RAW_DIFF,
                ),
                "read_diff_window": read_only_tool(
                    "read_diff_window",
                    purpose="Read a bounded diff window.",
                    scope=AgentToolScope.RAW_DIFF,
                    max_output_chars=64_000,
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
