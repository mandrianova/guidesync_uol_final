from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from guidesync_agent.tools.knowledge import (
    get_knowledge_document_ref,
    read_knowledge_document_window,
    search_knowledge_base,
)
from guidesync_agent.tools.repository import (
    list_changed_files,
    read_diff_window,
    read_file_window,
    search_repository,
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

    def repository_tools(self) -> dict[str, ToolCallable]:
        return {
            "list_changed_files": list_changed_files,
            "read_file_window": read_file_window,
            "read_diff_window": read_diff_window,
            "search_repository": search_repository,
        }

    def knowledge_tools(self) -> dict[str, ToolCallable]:
        return {
            "search_knowledge_base": search_knowledge_base,
            "get_knowledge_document_ref": get_knowledge_document_ref,
            "read_knowledge_document_window": read_knowledge_document_window,
        }
