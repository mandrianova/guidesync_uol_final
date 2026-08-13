from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.token import Token


@dataclass(frozen=True)
class MarkdownHeading:
    level: int
    text: str
    slug: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class MarkdownSection:
    title: str
    level: int
    start_line: int
    end_line: int
    text: str


@dataclass(frozen=True)
class MarkdownSectionBounds:
    start: int
    end: int
    level: int


@dataclass(frozen=True)
class MarkdownSignals:
    visible_text: str
    headings: list[str]
    paragraphs: list[str]
    inline_code_terms: list[str]
    fenced_code_bodies: list[str]
    link_labels: list[str]
    image_alt_texts: list[str]


def normalize_markdown(text: str, *, normalize_unicode: bool = False) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalize_unicode:
        return unicodedata.normalize("NFKC", normalized)
    return normalized


def normalize_heading(heading: str) -> str:
    return re.sub(r"\s+", " ", heading).strip().casefold()


def markdown_headings(markdown: str) -> list[MarkdownHeading]:
    tokens = _parse(markdown)
    headings: list[MarkdownHeading] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        inline = _next_inline(tokens, index)
        text = _inline_plain_text(inline.children if inline else None).strip()
        if not text:
            continue
        start_line, end_line = _token_lines(token)
        headings.append(
            MarkdownHeading(
                level=_heading_level(token),
                text=text,
                slug=slugify_heading(text),
                start_line=start_line,
                end_line=end_line,
            )
        )
    return headings


def first_heading(markdown: str) -> str | None:
    headings = markdown_headings(markdown)
    if not headings:
        return None
    return headings[0].text


def split_markdown_sections(markdown: str) -> list[MarkdownSection]:
    normalized = normalize_markdown(markdown)
    lines = normalized.splitlines()
    line_count = max(len(lines), 1)
    headings = markdown_headings(normalized)
    if not headings:
        return [
            MarkdownSection(
                title="Document",
                level=0,
                start_line=1,
                end_line=line_count,
                text=normalized,
            )
        ]

    sections: list[MarkdownSection] = []
    for index, heading in enumerate(headings):
        next_start_line = (
            headings[index + 1].start_line if index + 1 < len(headings) else line_count + 1
        )
        start_index = heading.start_line - 1
        end_index = next_start_line - 1
        sections.append(
            MarkdownSection(
                title=heading.text,
                level=heading.level,
                start_line=heading.start_line,
                end_line=max(heading.start_line, next_start_line - 1),
                text="\n".join(lines[start_index:end_index]),
            )
        )
    return sections


def markdown_section_exists(markdown: str, heading: str) -> bool:
    return find_section_bounds(markdown, heading) is not None


def find_section_bounds(markdown: str, heading: str) -> MarkdownSectionBounds | None:
    matches = section_bounds_by_heading(markdown, heading)
    if not matches:
        return None
    return matches[0]


def section_bounds_by_heading(markdown: str, heading: str) -> list[MarkdownSectionBounds]:
    normalized_heading = normalize_heading(heading)
    headings = markdown_headings(markdown)
    line_count = len(normalize_markdown(markdown).splitlines(keepends=True))
    matches: list[MarkdownSectionBounds] = []
    for index, candidate in enumerate(headings):
        if normalize_heading(candidate.text) != normalized_heading:
            continue
        end_index = line_count
        for following in headings[index + 1 :]:
            if following.level <= candidate.level:
                end_index = following.start_line - 1
                break
        matches.append(
            MarkdownSectionBounds(
                start=candidate.start_line - 1,
                end=end_index,
                level=candidate.level,
            )
        )
    return matches


def remove_markdown_sections(markdown: str, heading: str) -> str:
    lines = normalize_markdown(markdown).splitlines(keepends=True)
    for bounds in reversed(section_bounds_by_heading(markdown, heading)):
        del lines[bounds.start : bounds.end]
    return "".join(lines).rstrip() + "\n" if lines else ""


def replace_markdown_section(markdown: str, heading: str, replacement: str) -> str:
    existing = remove_duplicate_markdown_sections(markdown, heading)
    bounds = find_section_bounds(existing, heading)
    normalized_replacement = replacement.rstrip() + "\n"
    if bounds is None:
        if not existing.strip():
            return normalized_replacement
        return f"{existing.rstrip()}\n\n{normalized_replacement}"
    lines = normalize_markdown(existing).splitlines(keepends=True)
    lines[bounds.start : bounds.end] = [normalized_replacement]
    return "".join(lines).rstrip() + "\n"


def remove_duplicate_markdown_sections(markdown: str, heading: str) -> str:
    bounds = section_bounds_by_heading(markdown, heading)
    if len(bounds) <= 1:
        return markdown
    lines = normalize_markdown(markdown).splitlines(keepends=True)
    for duplicate in reversed(bounds[1:]):
        del lines[duplicate.start : duplicate.end]
    return "".join(lines)


def extract_markdown_signals(markdown: str) -> MarkdownSignals:
    normalized = normalize_markdown(markdown, normalize_unicode=True)
    tokens = _parse(normalized)
    headings = [heading.text for heading in markdown_headings(normalized)]
    visible_parts: list[str] = []
    paragraphs: list[str] = []
    inline_code_terms: list[str] = []
    fenced_code_bodies: list[str] = []
    link_labels: list[str] = []
    image_alt_texts: list[str] = []

    for index, token in enumerate(tokens):
        if token.type in {"fence", "code_block"}:
            fenced_code_bodies.append(token.content)
            continue
        if token.type != "inline":
            continue
        text = _inline_plain_text(token.children).strip()
        if text:
            visible_parts.append(text)
        if _previous_block_type(tokens, index) == "paragraph_open" and text:
            paragraphs.append(text)
        child_signals = _inline_signals(token.children)
        inline_code_terms.extend(child_signals.inline_code_terms)
        link_labels.extend(child_signals.link_labels)
        image_alt_texts.extend(child_signals.image_alt_texts)

    return MarkdownSignals(
        visible_text=re.sub(r"\s+", " ", " ".join(visible_parts)).strip(),
        headings=headings,
        paragraphs=paragraphs,
        inline_code_terms=inline_code_terms,
        fenced_code_bodies=fenced_code_bodies,
        link_labels=link_labels,
        image_alt_texts=image_alt_texts,
    )


def slugify_heading(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_heading(value))
    return slug.strip("-") or "section"


def _markdown() -> MarkdownIt:
    parser = MarkdownIt("default", {"html": False, "linkify": False, "typographer": False})
    parser.enable("table")
    return parser


def _parse(markdown: str) -> list[Token]:
    return _markdown().parse(mask_yaml_frontmatter(normalize_markdown(markdown)))


def mask_yaml_frontmatter(markdown: str) -> str:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return markdown
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() in {"---", "..."}),
        None,
    )
    if closing_index is None:
        return markdown
    lines[: closing_index + 1] = [""] * (closing_index + 1)
    return "\n".join(lines)


def _heading_level(token: Token) -> int:
    if token.tag.startswith("h") and token.tag[1:].isdigit():
        return int(token.tag[1:])
    return 1


def _token_lines(token: Token) -> tuple[int, int]:
    if token.map is None:
        return 1, 1
    return token.map[0] + 1, token.map[1]


def _next_inline(tokens: list[Token], start: int) -> Token | None:
    for token in tokens[start + 1 :]:
        if token.type == "inline":
            return token
        if token.nesting < 0:
            return None
    return None


def _previous_block_type(tokens: list[Token], index: int) -> str:
    if index == 0:
        return ""
    return tokens[index - 1].type


@dataclass(frozen=True)
class _InlineSignalLists:
    inline_code_terms: list[str]
    link_labels: list[str]
    image_alt_texts: list[str]


def _inline_signals(children: list[Token] | None) -> _InlineSignalLists:
    inline_code_terms: list[str] = []
    link_labels: list[str] = []
    image_alt_texts: list[str] = []
    child_tokens = children or []
    index = 0
    while index < len(child_tokens):
        child = child_tokens[index]
        if child.type == "code_inline" and child.content.strip():
            inline_code_terms.append(child.content.strip())
        elif child.type == "image":
            alt_text = _inline_plain_text(child.children).strip() or child.content.strip()
            if alt_text:
                image_alt_texts.append(alt_text)
        elif child.type == "link_open":
            close_index = _matching_inline_close(child_tokens, index, "link_close")
            label = _inline_plain_text(child_tokens[index + 1 : close_index]).strip()
            if label:
                link_labels.append(label)
            nested = _inline_signals(child_tokens[index + 1 : close_index])
            inline_code_terms.extend(nested.inline_code_terms)
            link_labels.extend(nested.link_labels)
            image_alt_texts.extend(nested.image_alt_texts)
            index = close_index
        else:
            nested = _inline_signals(child.children)
            inline_code_terms.extend(nested.inline_code_terms)
            link_labels.extend(nested.link_labels)
            image_alt_texts.extend(nested.image_alt_texts)
        index += 1
    return _InlineSignalLists(inline_code_terms, link_labels, image_alt_texts)


def _matching_inline_close(tokens: list[Token], start: int, close_type: str) -> int:
    for index in range(start + 1, len(tokens)):
        if tokens[index].type == close_type:
            return index
    return len(tokens)


def _inline_plain_text(children: list[Token] | None) -> str:
    parts: list[str] = []
    for child in children or []:
        if child.type in {"text", "code_inline"}:
            parts.append(child.content)
        elif child.type == "image":
            parts.append(_inline_plain_text(child.children) or child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append(" ")
        elif child.children:
            parts.append(_inline_plain_text(child.children))
        elif child.nesting == 0 and child.content:
            parts.append(child.content)
    return re.sub(r"\s+", " ", " ".join(part for part in parts if part)).strip()
