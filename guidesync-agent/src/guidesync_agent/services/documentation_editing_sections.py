from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict


class MarkdownSectionBounds(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: int
    end: int
    level: int


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def first_markdown_heading(markdown: str) -> str | None:
    for line in markdown.splitlines():
        match = HEADING_RE.match(line.strip())
        if match:
            return match.group(2).strip()
    return None


def markdown_section_exists(markdown: str, heading: str) -> bool:
    return find_section_bounds(markdown, heading) is not None


def remove_markdown_sections(markdown: str, heading: str) -> str:
    lines = markdown.splitlines(keepends=True)
    normalized_heading = normalize_heading(heading)
    while True:
        bounds = find_section_bounds_in_lines(lines, normalized_heading)
        if bounds is None:
            break
        del lines[bounds.start : bounds.end]
    return "".join(lines).rstrip() + "\n" if lines else ""


def replace_markdown_section(markdown: str, heading: str, replacement: str) -> str:
    existing = remove_duplicate_sections(markdown, heading)
    lines = existing.splitlines(keepends=True)
    bounds = find_section_bounds_in_lines(lines, normalize_heading(heading))
    normalized_replacement = replacement.rstrip() + "\n"
    if bounds is None:
        return f"{existing.rstrip()}\n\n{normalized_replacement}"
    lines[bounds.start : bounds.end] = [normalized_replacement]
    return "".join(lines).rstrip() + "\n"


def remove_duplicate_sections(markdown: str, heading: str) -> str:
    lines = markdown.splitlines(keepends=True)
    normalized_heading = normalize_heading(heading)
    first = find_section_bounds_in_lines(lines, normalized_heading)
    if first is None:
        return markdown
    search_from = first.end
    while True:
        duplicate = find_section_bounds_in_lines(lines, normalized_heading, start_at=search_from)
        if duplicate is None:
            break
        del lines[duplicate.start : duplicate.end]
    return "".join(lines)


def find_section_bounds(markdown: str, heading: str) -> MarkdownSectionBounds | None:
    return find_section_bounds_in_lines(
        markdown.splitlines(keepends=True),
        normalize_heading(heading),
    )


def find_section_bounds_in_lines(
    lines: list[str],
    normalized_heading: str,
    *,
    start_at: int = 0,
) -> MarkdownSectionBounds | None:
    for index in range(start_at, len(lines)):
        match = HEADING_RE.match(lines[index].strip())
        if not match or normalize_heading(match.group(2)) != normalized_heading:
            continue
        level = len(match.group(1))
        end = next_section_start(lines, index + 1, level)
        return MarkdownSectionBounds(start=index, end=end, level=level)
    return None


def next_section_start(lines: list[str], start_at: int, level: int) -> int:
    for index in range(start_at, len(lines)):
        match = HEADING_RE.match(lines[index].strip())
        if match and len(match.group(1)) <= level:
            return index
    return len(lines)


def normalize_heading(heading: str) -> str:
    return re.sub(r"\s+", " ", heading).strip().lower()
