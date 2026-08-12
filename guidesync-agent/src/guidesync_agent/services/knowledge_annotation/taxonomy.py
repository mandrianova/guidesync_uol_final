from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from guidesync_agent.schemas import (
    KnowledgeAnnotationEdgeType,
    KnowledgeAnnotationTargetType,
    KnowledgeConceptKind,
    ProjectTaxonomy,
    ProjectTaxonomyBootstrapStatus,
)
from guidesync_agent.services.text_normalization import tokenize_text

from .constants import BOOTSTRAP_HINTS
from .models import SemanticKeyphraseRanker, TaxonomyItem, TaxonomyMatch
from .utils import (
    dedupe_display,
    display_keyphrase,
    normalize_phrase,
    strong_candidate_concept,
    token_overlap_score,
)


@dataclass(frozen=True)
class TaxonomyMappingInput:
    keyphrases: Sequence[str]
    names: Sequence[str]
    taxonomy: ProjectTaxonomy
    semantic_ranker: SemanticKeyphraseRanker
    source_text: str


def map_to_taxonomy(mapping: TaxonomyMappingInput) -> list[TaxonomyMatch]:
    terms = dedupe_display([*mapping.keyphrases, *mapping.names])
    items = taxonomy_items(mapping.taxonomy)
    semantic_scores = mapping.semantic_ranker.rank(
        mapping.source_text,
        taxonomy_semantic_candidates(mapping),
    )

    return taxonomy_matches(mapping, terms, items, semantic_scores)


def map_to_taxonomy_with_scores(
    mapping: TaxonomyMappingInput,
    semantic_scores: dict[str, float],
) -> list[TaxonomyMatch]:
    return taxonomy_matches(
        mapping,
        dedupe_display([*mapping.keyphrases, *mapping.names]),
        taxonomy_items(mapping.taxonomy),
        semantic_scores,
    )


def taxonomy_semantic_candidates(mapping: TaxonomyMappingInput) -> list[str]:
    return [item.canonical for item in taxonomy_items(mapping.taxonomy)]


def taxonomy_matches(
    mapping: TaxonomyMappingInput,
    terms: list[str],
    items: list[TaxonomyItem],
    semantic_scores: dict[str, float],
) -> list[TaxonomyMatch]:
    matches: dict[tuple[KnowledgeConceptKind, str], TaxonomyMatch] = {}

    for item in items:
        for match in taxonomy_matches_for_item(item, terms, semantic_scores):
            retain_stronger_match(matches, match)
    for match in candidate_taxonomy_matches(terms, matches):
        matches.setdefault((match.kind, match.canonical), match)
    return sorted(matches.values(), key=lambda item: (-item.confidence, item.kind, item.canonical))


def taxonomy_matches_for_item(
    item: TaxonomyItem,
    terms: Sequence[str],
    semantic_scores: dict[str, float],
) -> list[TaxonomyMatch]:
    return [
        match
        for term in terms
        if (match := taxonomy_match_for_term(item, term, semantic_scores)) is not None
    ]


def taxonomy_match_for_term(
    item: TaxonomyItem,
    term: str,
    semantic_scores: dict[str, float],
) -> TaxonomyMatch | None:
    term_normalized = normalize_phrase(term)
    if not term_normalized:
        return None
    confidence, source = taxonomy_match_score(item, term_normalized, semantic_scores)
    if confidence == 0.0:
        return None
    needs_review = False
    if (
        item.bootstrap_status
        and item.bootstrap_status != ProjectTaxonomyBootstrapStatus.SELECTED
    ):
        confidence = min(confidence, 0.48)
        source = f"bootstrap-{item.bootstrap_status}"
        needs_review = True
    return TaxonomyMatch(
        kind=item.kind,
        canonical=item.canonical,
        confidence=confidence,
        source=source,
        needs_review=needs_review,
    )


def taxonomy_match_score(
    item: TaxonomyItem,
    term_normalized: str,
    semantic_scores: dict[str, float],
) -> tuple[float, str]:
    item_normalized = normalize_phrase(item.canonical)
    aliases = {normalize_phrase(alias) for alias in item.aliases}
    overlap = token_overlap_score(
        set(term_normalized.split()),
        set(tokenize_text(item.canonical)),
    )
    semantic = semantic_scores.get(item.canonical, 0.0)
    score = (0.0, "")
    if term_normalized == item_normalized:
        score = (0.94, "taxonomy-exact")
    elif term_normalized in aliases:
        score = (0.91, "taxonomy-alias")
    elif overlap >= 0.5:
        score = (0.76, "taxonomy-token-overlap")
    elif semantic >= 0.45:
        score = (0.68, "taxonomy-semantic-similarity")
    return score


def retain_stronger_match(
    matches: dict[tuple[KnowledgeConceptKind, str], TaxonomyMatch],
    match: TaxonomyMatch,
) -> None:
    key = (match.kind, match.canonical)
    if key not in matches or matches[key].confidence < match.confidence:
        matches[key] = match


def candidate_taxonomy_matches(
    terms: Sequence[str],
    existing: dict[tuple[KnowledgeConceptKind, str], TaxonomyMatch],
) -> list[TaxonomyMatch]:
    candidates = []
    matched_terms = {match.canonical for match in existing.values()}
    for term in terms[:8]:
        normalized = normalize_phrase(term)
        if not normalized or term in matched_terms:
            continue
        source, confidence = candidate_match_source(normalized, term)
        if source:
            candidates.append(
                TaxonomyMatch(
                    kind=KnowledgeConceptKind.CANDIDATE,
                    canonical=display_keyphrase(term),
                    confidence=confidence,
                    source=source,
                    needs_review=True,
                )
            )
    return candidates


def candidate_match_source(normalized: str, term: str) -> tuple[str, float]:
    if normalized.replace(" ", "-") in BOOTSTRAP_HINTS:
        return "bootstrap-candidate", 0.42
    if strong_candidate_concept(term):
        return "unmatched-strong-candidate", 0.46
    return "", 0.0


def taxonomy_items(taxonomy: ProjectTaxonomy) -> list[TaxonomyItem]:
    aliases = {normalize_phrase(item.canonical): tuple(item.aliases) for item in taxonomy.aliases}
    items: list[TaxonomyItem] = []
    for category in taxonomy.categories:
        items.append(
            TaxonomyItem(
                kind=KnowledgeConceptKind.CATEGORY,
                canonical=category,
                aliases=aliases.get(normalize_phrase(category), ()),
            )
        )
    for component in taxonomy.components:
        items.append(
            TaxonomyItem(
                kind=KnowledgeConceptKind.COMPONENT,
                canonical=component,
                aliases=aliases.get(normalize_phrase(component), ()),
            )
        )
    for workflow in taxonomy.workflows:
        items.append(
            TaxonomyItem(
                kind=KnowledgeConceptKind.WORKFLOW,
                canonical=workflow,
                aliases=aliases.get(normalize_phrase(workflow), ()),
            )
        )
    for area in taxonomy.documentation_areas:
        items.append(
            TaxonomyItem(
                kind=KnowledgeConceptKind.DOCUMENTATION_AREA,
                canonical=area,
                aliases=aliases.get(normalize_phrase(area), ()),
            )
        )
    for term in taxonomy.domain_terms:
        items.append(
            TaxonomyItem(
                kind=KnowledgeConceptKind.DOMAIN_TERM,
                canonical=term,
                aliases=aliases.get(normalize_phrase(term), ()),
            )
        )
    for hint in taxonomy.bootstrap_hints:
        if normalize_phrase(hint.value) not in {normalize_phrase(item.canonical) for item in items}:
            items.append(
                TaxonomyItem(
                    kind=KnowledgeConceptKind.CATEGORY
                    if hint.status == ProjectTaxonomyBootstrapStatus.SELECTED
                    else KnowledgeConceptKind.CANDIDATE,
                    canonical=hint.value,
                    bootstrap_status=hint.status,
                )
            )
    return items


def edge_for_taxonomy_match(
    match: TaxonomyMatch,
) -> tuple[KnowledgeAnnotationEdgeType, KnowledgeAnnotationTargetType]:
    if match.kind == KnowledgeConceptKind.CATEGORY:
        return KnowledgeAnnotationEdgeType.IN_CATEGORY, KnowledgeAnnotationTargetType.CATEGORY
    if match.kind == KnowledgeConceptKind.COMPONENT:
        return (
            KnowledgeAnnotationEdgeType.DESCRIBES_COMPONENT,
            KnowledgeAnnotationTargetType.COMPONENT,
        )
    if match.kind == KnowledgeConceptKind.WORKFLOW:
        return KnowledgeAnnotationEdgeType.COVERS_WORKFLOW, KnowledgeAnnotationTargetType.WORKFLOW
    if match.kind == KnowledgeConceptKind.DOCUMENTATION_AREA:
        return (
            KnowledgeAnnotationEdgeType.BELONGS_TO_DOC_AREA,
            KnowledgeAnnotationTargetType.DOCUMENTATION_AREA,
        )
    return KnowledgeAnnotationEdgeType.MAPS_TO_CONCEPT, KnowledgeAnnotationTargetType.CONCEPT


def aliases_for(canonical: str, taxonomy: ProjectTaxonomy) -> list[str]:
    normalized = normalize_phrase(canonical)
    for alias in taxonomy.aliases:
        if normalize_phrase(alias.canonical) == normalized:
            return alias.aliases
    return []


def taxonomy_normalized_terms(taxonomy: ProjectTaxonomy) -> list[str]:
    values: list[str] = [
        *taxonomy.categories,
        *taxonomy.components,
        *taxonomy.workflows,
        *taxonomy.documentation_areas,
        *taxonomy.domain_terms,
    ]
    for alias in taxonomy.aliases:
        values.append(alias.canonical)
        values.extend(alias.aliases)
    return [normalize_phrase(value) for value in values if normalize_phrase(value)]
