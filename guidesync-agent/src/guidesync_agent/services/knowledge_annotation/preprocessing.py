from __future__ import annotations

import re
from collections.abc import Sequence

from guidesync_agent.knowledge_tagging import tokenize_identifier, tokenize_text
from guidesync_agent.services.markdown_document import extract_markdown_signals

from .constants import (
    PASCAL_CASE_RE,
    QUOTED_LABEL_RE,
    SENTENCE_SPLIT_RE,
    TITLE_LABEL_RE,
    WORKFLOW_VERBS,
)
from .models import AnnotationInput, PreprocessedText
from .utils import dedupe_display, display_keyphrase, normalize_phrase


def preprocess_markdown(text: str) -> PreprocessedText:
    signals = extract_markdown_signals(text)
    code_identifier_terms: list[str] = []
    for body in signals.fenced_code_bodies:
        if len(body) <= 600:
            code_identifier_terms.extend(identifier_terms(body))
    plain = re.sub(r"\s+", " ", signals.visible_text).strip()
    return PreprocessedText(
        analysis_text=plain,
        headings=signals.headings,
        paragraphs=signals.paragraphs,
        sentences=deterministic_sentences(plain),
        inline_code_terms=dedupe_display(signals.inline_code_terms),
        code_identifier_terms=dedupe_display(code_identifier_terms),
        link_labels=dedupe_display(signals.link_labels),
        image_alt_texts=dedupe_display(signals.image_alt_texts),
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
