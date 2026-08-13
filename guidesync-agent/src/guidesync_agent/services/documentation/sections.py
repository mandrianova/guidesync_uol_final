from __future__ import annotations

from guidesync_agent.services.documentation.markdown import (
    MarkdownSectionBounds,
    find_section_bounds,
    first_heading,
    markdown_section_exists,
    normalize_heading,
    remove_duplicate_markdown_sections,
    remove_markdown_sections,
    replace_markdown_section,
)

__all__ = [
    "MarkdownSectionBounds",
    "find_section_bounds",
    "first_markdown_heading",
    "markdown_section_exists",
    "normalize_heading",
    "remove_duplicate_sections",
    "remove_markdown_sections",
    "replace_markdown_section",
]


def first_markdown_heading(markdown: str) -> str | None:
    return first_heading(markdown)


def remove_duplicate_sections(markdown: str, heading: str) -> str:
    return remove_duplicate_markdown_sections(markdown, heading)
