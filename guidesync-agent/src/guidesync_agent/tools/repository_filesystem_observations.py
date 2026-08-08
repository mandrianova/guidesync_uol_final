from __future__ import annotations

from collections.abc import Callable
from typing import cast

from guidesync_agent.schemas import (
    AgentLoopObservation,
    AgentLoopToolCall,
    AgentLoopToolName,
    AgentToolResultStatus,
    JsonValue,
    RepositoryFilesystemContext,
    RepositoryFilesystemResult,
)
from guidesync_agent.tools import repository_filesystem
from guidesync_agent.tools.args import list_arg, string_arg

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
    *,
    max_read_chars: int | None = None,
    max_multiple_read_chars: int | None = None,
) -> AgentLoopObservation:
    executors: dict[AgentLoopToolName, Callable[[], RepositoryFilesystemResult]] = {
        AgentLoopToolName.LIST_ALLOWED_DIRECTORIES: lambda: (
            repository_filesystem.list_allowed_directories(context)
        ),
        AgentLoopToolName.LIST_DIRECTORY: lambda: repository_filesystem.list_directory(
            context,
            string_arg(call, "path"),
        ),
        AgentLoopToolName.LIST_DIRECTORY_WITH_SIZES: lambda: (
            repository_filesystem.list_directory_with_sizes(
                context,
                string_arg(call, "path"),
                sort_by=string_arg(call, "sortBy", "name"),
            )
        ),
        AgentLoopToolName.DIRECTORY_TREE: lambda: repository_filesystem.directory_tree(
            context,
            string_arg(call, "path"),
            exclude_patterns=list_arg(call, "excludePatterns") or None,
        ),
        AgentLoopToolName.SEARCH_FILES: lambda: repository_filesystem.search_files(
            context,
            string_arg(call, "path"),
            string_arg(call, "pattern"),
            exclude_patterns=list_arg(call, "excludePatterns") or None,
        ),
        AgentLoopToolName.READ_TEXT_FILE: lambda: repository_filesystem.read_text_file(
            context,
            string_arg(call, "path"),
            options=repository_filesystem.TextReadOptions(
                head=optional_int_arg(call, "head"),
                tail=optional_int_arg(call, "tail"),
                start_line=optional_int_arg(call, "startLine"),
                line_count=optional_int_arg(call, "lineCount"),
                max_chars=(
                    max_read_chars
                    if max_read_chars is not None
                    else repository_filesystem.MAX_READ_FILE_CHARS
                ),
            ),
        ),
        AgentLoopToolName.READ_MULTIPLE_FILES: lambda: repository_filesystem.read_multiple_files(
            context,
            list_arg(call, "paths"),
            **(
                {
                    "max_file_chars": max_multiple_read_chars,
                    "max_total_chars": max_multiple_read_chars,
                }
                if max_multiple_read_chars is not None
                else {}
            ),
        ),
        AgentLoopToolName.GET_FILE_INFO: lambda: repository_filesystem.get_file_info(
            context,
            string_arg(call, "path"),
        ),
    }
    executor = executors.get(call.tool_name)
    if executor is None:
        return unsupported_filesystem_observation(call)
    return filesystem_observation(call, executor())


def unsupported_filesystem_observation(call: AgentLoopToolCall) -> AgentLoopObservation:
    message = f"Unsupported repository filesystem tool: {call.tool_name.value}"
    return AgentLoopObservation(
        tool_name=call.tool_name,
        arguments=call.arguments,
        result_status=AgentToolResultStatus.UNSUPPORTED_TOOL,
        output_summary=message,
        error_code="unsupported_tool",
        error_message=message,
    )


def filesystem_observation(
    call: AgentLoopToolCall,
    result: RepositoryFilesystemResult,
) -> AgentLoopObservation:
    return AgentLoopObservation(
        tool_name=call.tool_name,
        arguments=call.arguments,
        result_status=(
            AgentToolResultStatus.SUCCESS
            if result.error is None
            else AgentToolResultStatus.TOOL_ERROR
        ),
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
    if result.error is not None:
        return f"{result.tool_name} failed: {result.error.message}"
    summaries: dict[str, Callable[[RepositoryFilesystemResult], str]] = {
        "list_allowed_directories": lambda item: f"{len(item.roots)} repository roots available",
        "list_directory": direct_entries_summary,
        "list_directory_with_sizes": direct_entries_summary,
        "directory_tree": lambda item: (
            f"{item.metadata.get('node_count', 0)} tree nodes under {item.path}; "
            f"truncated={item.truncated}"
        ),
        "search_files": lambda item: (
            f"{item.metadata.get('match_count', len(item.entries))} content matches under "
            f"{item.path}; truncated={item.truncated}"
        ),
        "read_text_file": lambda item: (
            f"{len(item.content)} chars from {item.path}; truncated={item.truncated}"
        ),
        "read_multiple_files": lambda item: (
            f"{item.metadata.get('returned_count', len(item.entries))} files read; "
            f"truncated={item.truncated}"
        ),
        "get_file_info": lambda item: f"metadata for {item.path}",
    }
    builder = summaries.get(result.tool_name)
    return builder(result) if builder else f"{result.tool_name} completed"


def direct_entries_summary(result: RepositoryFilesystemResult) -> str:
    return f"{len(result.entries)} direct entries under {result.path}; truncated={result.truncated}"


def optional_int_arg(call: AgentLoopToolCall, name: str) -> int | None:
    value = call.arguments.get(name)
    return value if isinstance(value, int) else None
