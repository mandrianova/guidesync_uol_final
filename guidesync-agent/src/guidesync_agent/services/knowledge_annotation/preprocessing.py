from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from guidesync_agent.knowledge_tagging import tokenize_identifier, tokenize_text

from .constants import (
    FENCED_CODE_RE,
    HEADING_RE,
    IMAGE_RE,
    INLINE_CODE_RE,
    LINK_RE,
    MARKDOWN_DECORATION_RE,
    PASCAL_CASE_RE,
    QUOTED_LABEL_RE,
    SENTENCE_SPLIT_RE,
    TITLE_LABEL_RE,
    WORKFLOW_VERBS,
)
from .models import AnnotationInput, PreprocessedText
from .utils import dedupe_display, display_keyphrase, normalize_phrase


def preprocess_markdown(text: str) -> PreprocessedText:
    normalized = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    headings = [match.group(1).strip(" #") for match in HEADING_RE.finditer(normalized)]
    code_identifier_terms: list[str] = []

    def replace_code_block(match: re.Match[str]) -> str:
        body = match.group("body")
        if len(body) <= 600:
            code_identifier_terms.extend(identifier_terms(body))
        return "\n "

    without_code_blocks = FENCED_CODE_RE.sub(replace_code_block, normalized)
    image_alt_texts = [
        match.group(1).strip() for match in IMAGE_RE.finditer(without_code_blocks) if match.group(1)
    ]
    without_images = IMAGE_RE.sub(lambda match: f" {match.group(1)} ", without_code_blocks)
    link_labels = [
        match.group(1).strip() for match in LINK_RE.finditer(without_images) if match.group(1)
    ]
    without_links = LINK_RE.sub(lambda match: f" {match.group(1)} ", without_images)
    inline_code_terms = [
        match.group(1).strip() for match in INLINE_CODE_RE.finditer(without_links) if match.group(1)
    ]
    without_inline_code = INLINE_CODE_RE.sub(lambda match: f" {match.group(1)} ", without_links)
    plain = MARKDOWN_DECORATION_RE.sub(" ", without_inline_code.replace("|", " "))
    plain = re.sub(r"\s+", " ", plain).strip()
    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n\s*\n", without_inline_code)
        if paragraph.strip()
    ]
    return PreprocessedText(
        analysis_text=plain,
        headings=headings,
        paragraphs=paragraphs,
        sentences=deterministic_sentences(plain),
        inline_code_terms=dedupe_display(inline_code_terms),
        code_identifier_terms=dedupe_display(code_identifier_terms),
        link_labels=dedupe_display(link_labels),
        image_alt_texts=dedupe_display(image_alt_texts),
    )


def identifier_terms(text: str) -> list[str]:
    terms: list[str] = []
    terms.extend(pascal_case_names(text))
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9_./:-]{2,}", text):
        if len(raw) > 120:
            continue
        tokens = tokenize_identifier(raw)
        if len(tokens) >= 2:
            terms.append(" ".join(tokens))
    return dedupe_display(terms)


def pascal_case_names(text: str) -> list[str]:
    return dedupe_display(match.group(0) for match in PASCAL_CASE_RE.finditer(text))


def label_names(text: str) -> list[str]:
    labels = [match.group(1).strip() for match in QUOTED_LABEL_RE.finditer(text)]
    labels.extend(match.group(0).strip() for match in TITLE_LABEL_RE.finditer(text))
    return dedupe_display(labels)


def workflow_phrases(headings: Sequence[str]) -> list[str]:
    phrases: list[str] = []
    for heading in headings:
        tokens = tokenize_text(heading)
        if not tokens or tokens[0] not in WORKFLOW_VERBS:
            continue
        phrase = " ".join(tokens[:4])
        if len(phrase.split()) >= 2:
            phrases.append(phrase)
    return phrases


def document_area_names(source: AnnotationInput, preprocessed: PreprocessedText) -> list[str]:
    values: list[str] = []
    for candidate in [source.heading or "", *preprocessed.headings, source.path or ""]:
        normalized = normalize_phrase(candidate)
        if any(term in normalized.split() for term in {"guide", "docs", "note", "readme", "setup"}):
            values.append(display_keyphrase(candidate))
    return values


def path_display_names(path: str) -> list[str]:
    names: list[str] = []
    for part in re.split(r"[/_.-]+", path):
        if not part or part.isdigit():
            continue
        if len(part) > 2:
            names.append(display_keyphrase(part))
    names.extend(pascal_case_names(path))
    return dedupe_display(names)


def ngram_phrases(tokens: Sequence[str], *, min_n: int, max_n: int) -> list[str]:
    phrases: list[str] = []
    token_list = [token for token in tokens if len(token) > 2]
    for size in range(min_n, max_n + 1):
        for index in range(0, max(len(token_list) - size + 1, 0)):
            phrase = " ".join(token_list[index : index + size])
            if len(set(phrase.split())) >= min_n:
                phrases.append(phrase)
    return dedupe_display(phrases)


def deterministic_sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]
