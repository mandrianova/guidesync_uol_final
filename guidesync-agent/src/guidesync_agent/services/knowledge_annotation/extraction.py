from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from guidesync_agent.schemas import ProjectTaxonomy
from guidesync_agent.services.text_normalization import tokenize_identifier, tokenize_text

from .constants import GENERIC_KEYPHRASE_TERMS
from .models import (
    AnnotationInput,
    NlpAnalysis,
    PhraseCandidate,
    PreprocessedText,
    SemanticKeyphraseRanker,
)
from .preprocessing import (
    document_area_names,
    label_names,
    ngram_phrases,
    pascal_case_names,
    path_display_names,
    workflow_phrases,
)
from .taxonomy import taxonomy_normalized_terms
from .utils import (
    clean_phrase,
    dedupe_display,
    filter_name,
    normalize_phrase,
)


def extract_keyphrases(
    source: AnnotationInput,
    preprocessed: PreprocessedText,
    analysis: NlpAnalysis,
    taxonomy: ProjectTaxonomy,
    semantic_ranker: SemanticKeyphraseRanker,
    *,
    limit: int = 12,
) -> list[PhraseCandidate]:
    candidates: dict[str, PhraseCandidate] = {}

    def add(value: str, source_label: str, score: float) -> None:
        cleaned = clean_phrase(value)
        normalized = normalize_phrase(cleaned)
        if not normalized or len(normalized.split()) < 2:
            return
        if normalized in GENERIC_KEYPHRASE_TERMS:
            return
        existing = candidates.get(normalized)
        candidate = PhraseCandidate(value=cleaned, source=source_label, score=score)
        if existing is None or candidate.score > existing.score:
            candidates[normalized] = candidate

    for heading in preprocessed.headings:
        add(heading, "heading", 0.64)
    if source.heading:
        add(source.heading, "heading", 0.68)
    for chunk in analysis.noun_chunks:
        add(chunk, "spacy-noun-chunk", 0.56)
    for entity in analysis.entities:
        add(entity.text, f"spacy-entity:{entity.label}", 0.58)
    for label in [*preprocessed.link_labels, *preprocessed.image_alt_texts]:
        add(label, "markdown-label", 0.52)
    for term in [*preprocessed.inline_code_terms, *preprocessed.code_identifier_terms]:
        add(" ".join(tokenize_identifier(term)) or term, "code-identifier", 0.48)
    for phrase in ngram_phrases(analysis.lemmas or analysis.tokens, min_n=2, max_n=4):
        add(phrase, "tfidf-ngram", 0.42)
    if source.path:
        add(" ".join(tokenize_identifier(source.path)), "path", 0.52)

    candidate_values = [candidate.value for candidate in candidates.values()]
    semantic_scores = semantic_ranker.rank(preprocessed.analysis_text, candidate_values)
    taxonomy_terms = set(taxonomy_normalized_terms(taxonomy))
    ranked = []
    text_counter = Counter(tokenize_text(preprocessed.analysis_text))
    for normalized, candidate in candidates.items():
        phrase_terms = normalized.split()
        frequency = sum(text_counter[term] for term in phrase_terms) / max(len(phrase_terms), 1)
        taxonomy_boost = 0.16 if normalized in taxonomy_terms else 0.0
        semantic_score = semantic_scores.get(candidate.value, 0.0)
        score = (
            candidate.score + min(frequency * 0.04, 0.12) + taxonomy_boost + semantic_score * 0.24
        )
        ranked.append(PhraseCandidate(value=candidate.value, source=candidate.source, score=score))
    return sorted(ranked, key=lambda item: (-item.score, item.value.lower()))[:limit]


def extract_names(
    source: AnnotationInput,
    preprocessed: PreprocessedText,
    analysis: NlpAnalysis,
    *,
    limit: int = 16,
) -> list[str]:
    names: list[str] = []
    names.extend(pascal_case_names(source.text))
    names.extend(preprocessed.inline_code_terms)
    names.extend(preprocessed.code_identifier_terms)
    names.extend(label_names(source.text))
    names.extend(entity.text for entity in analysis.entities)
    names.extend(workflow_phrases(preprocessed.headings))
    names.extend(document_area_names(source, preprocessed))
    if source.path:
        names.extend(path_display_names(source.path))
    return dedupe_display(filter_name(value) for value in names if filter_name(value))[:limit]


def extract_tags(
    analysis: NlpAnalysis,
    keyphrases: Sequence[PhraseCandidate],
    limit: int = 10,
) -> list[str]:
    counts = Counter(analysis.lemmas or analysis.tokens)
    for phrase in keyphrases:
        counts.update(normalize_phrase(phrase.value).split())
    return [
        term
        for term, _ in counts.most_common(limit)
        if len(term) > 2 and term not in GENERIC_KEYPHRASE_TERMS
    ]
