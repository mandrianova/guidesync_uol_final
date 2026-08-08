from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic_ai import Agent, RunContext

from guidesync_agent.schemas import AgentLoopToolCall, AgentLoopToolName

FilesystemToolExecutor = Callable[[RunContext[Any], AgentLoopToolCall], str]


def register_repository_filesystem_tools(
    agent: Agent[Any, Any],
    execute: FilesystemToolExecutor,
) -> None:
    register_directory_tools(agent, execute)
    register_search_tool(agent, execute)
    register_file_read_tools(agent, execute)


def register_directory_tools(
    agent: Agent[Any, Any],
    execute: FilesystemToolExecutor,
) -> None:
    @agent.tool
    def list_allowed_directories(ctx: RunContext[Any]) -> str:
        """List the virtual repository roots available to this agent.

        Use this first. Returned paths look like /repositories/<repository_id>/ and
        are the only valid roots for the repository filesystem tools.
        """
        return execute(
            ctx,
            AgentLoopToolCall(tool_name=AgentLoopToolName.LIST_ALLOWED_DIRECTORIES),
        )

    @agent.tool
    def list_directory(ctx: RunContext[Any], path: str) -> str:
        """List direct children of one virtual repository directory.

        Args:
            path: Virtual directory path, for example /repositories/repo-id/src.

        Returns terminal-like [DIR]/[FILE] lines. This is intentionally shallow;
        use directory_tree for focused recursive structure.
        """
        return execute(
            ctx,
            AgentLoopToolCall(
                tool_name=AgentLoopToolName.LIST_DIRECTORY,
                arguments={"path": path},
            ),
        )


def register_search_tool(
    agent: Agent[Any, Any],
    execute: FilesystemToolExecutor,
) -> None:
    @agent.tool
    def list_directory_with_sizes(
        ctx: RunContext[Any],
        path: str,
        sortBy: str = "name",  # noqa: N803 - model-facing tool schema
    ) -> str:
        """List direct children of one virtual directory with byte sizes.

        Args:
            path: Virtual directory path, for example /repositories/repo-id/docs.
            sortBy: Either "name" or "size".

        Use this to spot large files before reading them.
        """
        return execute(
            ctx,
            AgentLoopToolCall(
                tool_name=AgentLoopToolName.LIST_DIRECTORY_WITH_SIZES,
                arguments={"path": path, "sortBy": sortBy},
            ),
        )

    @agent.tool
    def directory_tree(
        ctx: RunContext[Any],
        path: str,
        excludePatterns: list[str] | None = None,  # noqa: N803 - tool schema
    ) -> str:
        """Return a bounded recursive JSON tree for a focused virtual directory.

        Args:
            path: Virtual directory path to expand.
            excludePatterns: Optional glob-style names or relative paths to skip.

        Use this for structure and path discovery after narrowing to a subtree.
        It is bounded and may truncate on broad directories.
        """
        args: dict[str, Any] = {"path": path}
        if excludePatterns:
            args["excludePatterns"] = excludePatterns
        return execute(
            ctx,
            AgentLoopToolCall(
                tool_name=AgentLoopToolName.DIRECTORY_TREE,
                arguments=args,
            ),
        )

    @agent.tool
    def search_files(
        ctx: RunContext[Any],
        path: str,
        pattern: str,
        excludePatterns: list[str] | None = None,  # noqa: N803 - tool schema
    ) -> str:
        """Grep-like search for text inside virtual repository files.

        Args:
            path: Virtual file or directory path to search recursively.
            pattern: Case-insensitive literal text to find in file contents.
            excludePatterns: Optional glob-style names or relative paths to skip.

        Returns lines in the form /repositories/<id>/path:line: preview. The
        implementation uses ripgrep internally, scoped to the resolved virtual
        repository path. Binary, oversized, .git, and explicitly excluded files
        are skipped.
        """
        args: dict[str, Any] = {"path": path, "pattern": pattern}
        if excludePatterns:
            args["excludePatterns"] = excludePatterns
        return execute(
            ctx,
            AgentLoopToolCall(tool_name=AgentLoopToolName.SEARCH_FILES, arguments=args),
        )


def register_file_read_tools(
    agent: Agent[Any, Any],
    execute: FilesystemToolExecutor,
) -> None:
    @agent.tool
    def read_text_file(  # noqa: PLR0913 - flat model-facing tool contract
        ctx: RunContext[Any],
        path: str,
        head: int | None = None,
        tail: int | None = None,
        startLine: int | None = None,  # noqa: N803 - model-facing tool schema
        lineCount: int | None = None,  # noqa: N803 - model-facing tool schema
    ) -> str:
        """Read one virtual repository text file.

        Args:
            path: Virtual file path, for example /repositories/repo-id/README.md.
            head: Optional first N lines to read. Cannot be combined with tail.
            tail: Optional last N lines to read. Cannot be combined with head.
            startLine: Optional 1-based first line for a focused window.
            lineCount: Number of lines to return from startLine (defaults to 200).

        Use search_files or directory_tree first when the exact path is unknown.
        """
        args: dict[str, Any] = {"path": path}
        if head is not None:
            args["head"] = head
        if tail is not None:
            args["tail"] = tail
        if startLine is not None:
            args["startLine"] = startLine
        if lineCount is not None:
            args["lineCount"] = lineCount
        return execute(
            ctx,
            AgentLoopToolCall(tool_name=AgentLoopToolName.READ_TEXT_FILE, arguments=args),
        )

    @agent.tool
    def read_multiple_files(ctx: RunContext[Any], paths: list[str]) -> str:
        """Read several virtual repository text files in one bounded response.

        Args:
            paths: Virtual file paths. Each file is read independently and failures
                are returned inline instead of aborting the whole call.
        """
        return execute(
            ctx,
            AgentLoopToolCall(
                tool_name=AgentLoopToolName.READ_MULTIPLE_FILES,
                arguments={"paths": paths},
            ),
        )

    @agent.tool
    def get_file_info(ctx: RunContext[Any], path: str) -> str:
        """Return filesystem metadata for one virtual repository file or directory.

        Args:
            path: Virtual repository path to inspect.
        """
        return execute(
            ctx,
            AgentLoopToolCall(
                tool_name=AgentLoopToolName.GET_FILE_INFO,
                arguments={"path": path},
            ),
        )
