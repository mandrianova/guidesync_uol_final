from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from guidesync_agent.schemas import ProjectTaxonomy
from guidesync_agent.services.text_normalization import tokenize_identifier, tokenize_text

from .constants import GENERIC_KEYPHRASE_TERMS, MAX_SEMANTIC_KEYPHRASE_CANDIDATES
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


@dataclass(frozen=True)
class KeyphraseExtractionInput:
    source: AnnotationInput
    preprocessed: PreprocessedText
    analysis: NlpAnalysis
    taxonomy: ProjectTaxonomy
    semantic_ranker: SemanticKeyphraseRanker
    limit: int = 12


@dataclass(frozen=True)
class PreparedKeyphraseExtraction:
    extraction: KeyphraseExtractionInput
    candidates: dict[str, PhraseCandidate]
    semantic_candidates: list[str]


def extract_keyphrases(
    extraction: KeyphraseExtractionInput,
) -> list[PhraseCandidate]:
    prepared = prepare_keyphrase_extraction(extraction)
    semantic_scores = extraction.semantic_ranker.rank(
        extraction.preprocessed.analysis_text,
        prepared.semantic_candidates,
    )
    return complete_keyphrase_extraction(prepared, semantic_scores)


def prepare_keyphrase_extraction(
    extraction: KeyphraseExtractionInput,
) -> PreparedKeyphraseExtraction:
    candidates = collect_keyphrase_candidates(extraction)
    candidate_values = semantic_keyphrase_candidates(candidates, extraction)
    return PreparedKeyphraseExtraction(
        extraction=extraction,
        candidates=candidates,
        semantic_candidates=candidate_values,
    )


def complete_keyphrase_extraction(
    prepared: PreparedKeyphraseExtraction,
    semantic_scores: dict[str, float],
) -> list[PhraseCandidate]:
    return rank_keyphrase_candidates(
        prepared.candidates,
        prepared.extraction,
        semantic_scores,
    )


def semantic_keyphrase_candidates(
    candidates: dict[str, PhraseCandidate],
    extraction: KeyphraseExtractionInput,
) -> list[str]:
    text_counter = Counter(tokenize_text(extraction.preprocessed.analysis_text))
    taxonomy_terms = set(taxonomy_normalized_terms(extraction.taxonomy))
    ranked = sorted(
        candidates.items(),
        key=lambda item: (
            -keyphrase_base_score(item[0], item[1], text_counter, taxonomy_terms),
            item[1].value.lower(),
        ),
    )
    return [
        candidate.value
        for _, candidate in ranked[:MAX_SEMANTIC_KEYPHRASE_CANDIDATES]
    ]


def collect_keyphrase_candidates(
    extraction: KeyphraseExtractionInput,
) -> dict[str, PhraseCandidate]:
    candidates: dict[str, PhraseCandidate] = {}
    for value, source_label, score in keyphrase_sources(extraction):
        add_keyphrase_candidate(candidates, value, source_label, score)
    return candidates


def keyphrase_sources(
    extraction: KeyphraseExtractionInput,
) -> list[tuple[str, str, float]]:
    source = extraction.source
    preprocessed = extraction.preprocessed
    analysis = extraction.analysis
    values = [(heading, "heading", 0.64) for heading in preprocessed.headings]
    if source.heading:
        values.append((source.heading, "heading", 0.68))
    values.extend((chunk, "spacy-noun-chunk", 0.56) for chunk in analysis.noun_chunks)
    values.extend(
        (entity.text, f"spacy-entity:{entity.label}", 0.58) for entity in analysis.entities
    )
    values.extend(
        (label, "markdown-label", 0.52)
        for label in [*preprocessed.link_labels, *preprocessed.image_alt_texts]
    )
    values.extend(
        (" ".join(tokenize_identifier(term)) or term, "code-identifier", 0.48)
        for term in [*preprocessed.inline_code_terms, *preprocessed.code_identifier_terms]
    )
    values.extend(
        (phrase, "tfidf-ngram", 0.42)
        for phrase in ngram_phrases(analysis.lemmas or analysis.tokens, min_n=2, max_n=4)
    )
    if source.path:
        values.append((" ".join(tokenize_identifier(source.path)), "path", 0.52))
    return values


def add_keyphrase_candidate(
    candidates: dict[str, PhraseCandidate],
    value: str,
    source_label: str,
    score: float,
) -> None:
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


def rank_keyphrase_candidates(
    candidates: dict[str, PhraseCandidate],
    extraction: KeyphraseExtractionInput,
    semantic_scores: dict[str, float],
) -> list[PhraseCandidate]:
    taxonomy_terms = set(taxonomy_normalized_terms(extraction.taxonomy))
    ranked = []
    text_counter = Counter(tokenize_text(extraction.preprocessed.analysis_text))
    for normalized, candidate in candidates.items():
        semantic_score = semantic_scores.get(candidate.value, 0.0)
        score = keyphrase_base_score(
            normalized,
            candidate,
            text_counter,
            taxonomy_terms,
        ) + semantic_score * 0.24
        ranked.append(
            PhraseCandidate(value=candidate.value, source=candidate.source, score=score)
        )
    return sorted(ranked, key=lambda item: (-item.score, item.value.lower()))[
        : extraction.limit
    ]


def keyphrase_base_score(
    normalized: str,
    candidate: PhraseCandidate,
    text_counter: Counter[str],
    taxonomy_terms: set[str],
) -> float:
    phrase_terms = normalized.split()
    frequency = sum(text_counter[term] for term in phrase_terms) / max(len(phrase_terms), 1)
    taxonomy_boost = 0.16 if normalized in taxonomy_terms else 0.0
    return candidate.score + min(frequency * 0.04, 0.12) + taxonomy_boost


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
