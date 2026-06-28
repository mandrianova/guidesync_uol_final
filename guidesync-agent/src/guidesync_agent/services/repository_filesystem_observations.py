from __future__ import annotations

from typing import cast

from guidesync_agent.schemas import (
    AgentLoopObservation,
    AgentLoopToolCall,
    AgentLoopToolName,
    JsonValue,
    RepositoryFilesystemContext,
    RepositoryFilesystemResult,
)
from guidesync_agent.services.agent_loop_args import list_arg, string_arg
from guidesync_agent.tools import repository_filesystem

FILESYSTEM_TOOL_NAMES = {
    AgentLoopToolName.LIST_ALLOWED_DIRECTORIES,
    AgentLoopToolName.LIST_DIRECTORY,
    AgentLoopToolName.LIST_DIRECTORY_WITH_SIZES,
    AgentLoopToolName.DIRECTORY_TREE,
    AgentLoopToolName.SEARCH_FILES,
    AgentLoopToolName.READ_TEXT_FILE,
    AgentLoopToolName.READ_MULTIPLE_FILES,
    AgentLoopToolName.GET_FILE_INFO,
}


def execute_repository_filesystem_tool(
    context: RepositoryFilesystemContext,
    call: AgentLoopToolCall,
) -> AgentLoopObservation:
    if call.tool_name == AgentLoopToolName.LIST_ALLOWED_DIRECTORIES:
        result = repository_filesystem.list_allowed_directories(context)
    elif call.tool_name == AgentLoopToolName.LIST_DIRECTORY:
        result = repository_filesystem.list_directory(context, string_arg(call, "path"))
    elif call.tool_name == AgentLoopToolName.LIST_DIRECTORY_WITH_SIZES:
        result = repository_filesystem.list_directory_with_sizes(
            context,
            string_arg(call, "path"),
            sort_by=string_arg(call, "sortBy", "name"),
        )
    elif call.tool_name == AgentLoopToolName.DIRECTORY_TREE:
        result = repository_filesystem.directory_tree(
            context,
            string_arg(call, "path"),
            exclude_patterns=list_arg(call, "excludePatterns") or None,
        )
    elif call.tool_name == AgentLoopToolName.SEARCH_FILES:
        result = repository_filesystem.search_files(
            context,
            string_arg(call, "path"),
            string_arg(call, "pattern"),
            exclude_patterns=list_arg(call, "excludePatterns") or None,
        )
    elif call.tool_name == AgentLoopToolName.READ_TEXT_FILE:
        result = repository_filesystem.read_text_file(
            context,
            string_arg(call, "path"),
            head=optional_int_arg(call, "head"),
            tail=optional_int_arg(call, "tail"),
        )
    elif call.tool_name == AgentLoopToolName.READ_MULTIPLE_FILES:
        result = repository_filesystem.read_multiple_files(context, list_arg(call, "paths"))
    elif call.tool_name == AgentLoopToolName.GET_FILE_INFO:
        result = repository_filesystem.get_file_info(context, string_arg(call, "path"))
    else:
        return AgentLoopObservation(
            tool_name=call.tool_name,
            arguments=call.arguments,
            ok=False,
            output_summary=f"Unsupported repository filesystem tool: {call.tool_name.value}",
            error_code="unsupported_tool",
            error_message=f"Unsupported repository filesystem tool: {call.tool_name.value}",
        )
    return filesystem_observation(call, result)


def filesystem_observation(
    call: AgentLoopToolCall,
    result: RepositoryFilesystemResult,
) -> AgentLoopObservation:
    return AgentLoopObservation(
        tool_name=call.tool_name,
        arguments=call.arguments,
        ok=result.ok,
        output_summary=filesystem_summary(result),
        payload=cast(dict[str, JsonValue], result.model_dump(mode="json")),
        evidence_refs=result.evidence_refs,
        artifact_ref=result.artifact_ref,
        error_code=result.error.code if result.error else None,
        error_message=result.error.message if result.error else None,
    )


def model_visible_content(observation: AgentLoopObservation) -> str:
    content = observation.payload.get("content")
    if isinstance(content, str):
        return content
    if observation.error_message:
        return f"Error: {observation.error_message}"
    return observation.output_summary


def filesystem_summary(result: RepositoryFilesystemResult) -> str:
    if not result.ok and result.error is not None:
        return f"{result.tool_name} failed: {result.error.message}"
    if result.tool_name == "list_allowed_directories":
        return f"{len(result.roots)} repository roots available"
    if result.tool_name in {"list_directory", "list_directory_with_sizes"}:
        return (
            f"{len(result.entries)} direct entries under {result.path}; "
            f"truncated={result.truncated}"
        )
    if result.tool_name == "directory_tree":
        node_count = result.metadata.get("node_count", 0)
        return f"{node_count} tree nodes under {result.path}; truncated={result.truncated}"
    if result.tool_name == "search_files":
        match_count = result.metadata.get("match_count", len(result.entries))
        return f"{match_count} content matches under {result.path}; truncated={result.truncated}"
    if result.tool_name == "read_text_file":
        return f"{len(result.content)} chars from {result.path}; truncated={result.truncated}"
    if result.tool_name == "read_multiple_files":
        return (
            f"{result.metadata.get('returned_count', len(result.entries))} files read; "
            f"truncated={result.truncated}"
        )
    if result.tool_name == "get_file_info":
        return f"metadata for {result.path}"
    return f"{result.tool_name} completed"


def optional_int_arg(call: AgentLoopToolCall, name: str) -> int | None:
    value = call.arguments.get(name)
    return value if isinstance(value, int) else None
