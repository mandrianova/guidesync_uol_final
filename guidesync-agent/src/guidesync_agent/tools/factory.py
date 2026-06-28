from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from guidesync_agent.schemas import AgentToolDefinition
from guidesync_agent.services.agent_tool_registry import tool_factory_definitions
from guidesync_agent.tools.knowledge import (
    get_knowledge_document_ref,
    read_knowledge_document_window,
    search_knowledge_base,
)
from guidesync_agent.tools.repository import (
    list_changed_files,
    read_diff_window,
)
from guidesync_agent.tools.repository_filesystem import (
    context_from_project,
    directory_tree,
    get_file_info,
    list_allowed_directories,
    list_directory,
    list_directory_with_sizes,
    read_multiple_files,
    read_text_file,
    search_files,
)
from guidesync_agent.tools.validation import validate_tool_result

ToolCallable = Callable[..., Any]


@dataclass(frozen=True)
class ToolFactory:
    project_id: str

    def for_workflow(self, workflow: str) -> dict[str, ToolCallable]:
        tools: dict[str, ToolCallable] = {}
        if workflow in {"documentation_update", "project_profile", "model_comparison"}:
            tools.update(self.repository_tools())
            tools.update(self.knowledge_tools())
        tools["validate_tool_result"] = validate_tool_result
        return tools

    def definitions_for_workflow(self, workflow: str) -> dict[str, AgentToolDefinition]:
        return tool_factory_definitions(workflow)

    def repository_tools(self) -> dict[str, ToolCallable]:
        filesystem_context = context_from_project(self.project_id)
        return {
            "list_allowed_directories": lambda: list_allowed_directories(
                filesystem_context
            ),
            "list_directory": lambda path: list_directory(filesystem_context, path),
            "list_directory_with_sizes": lambda path, sortBy="name": list_directory_with_sizes(
                filesystem_context,
                path,
                sort_by=sortBy,
            ),
            "directory_tree": lambda path, excludePatterns=None: directory_tree(
                filesystem_context,
                path,
                exclude_patterns=excludePatterns,
            ),
            "search_files": lambda path, pattern, excludePatterns=None: search_files(
                filesystem_context,
                path,
                pattern,
                exclude_patterns=excludePatterns,
            ),
            "read_text_file": lambda path, head=None, tail=None: read_text_file(
                filesystem_context,
                path,
                head=head,
                tail=tail,
            ),
            "read_multiple_files": lambda paths: read_multiple_files(
                filesystem_context,
                paths,
            ),
            "get_file_info": lambda path: get_file_info(filesystem_context, path),
            "list_changed_files": list_changed_files,
            "read_diff_window": read_diff_window,
        }

    def knowledge_tools(self) -> dict[str, ToolCallable]:
        return {
            "search_knowledge_base": search_knowledge_base,
            "get_knowledge_document_ref": get_knowledge_document_ref,
            "read_knowledge_document_window": read_knowledge_document_window,
        }
