from __future__ import annotations

from collections.abc import Sequence

from guidesync_agent.knowledge_tagging import tokenize_text
from guidesync_agent.schemas import (
    KnowledgeAnnotationEdgeType,
    KnowledgeAnnotationTargetType,
    KnowledgeConceptKind,
    ProjectTaxonomy,
    ProjectTaxonomyBootstrapStatus,
)

from .constants import BOOTSTRAP_HINTS
from .models import SemanticKeyphraseRanker, TaxonomyItem, TaxonomyMatch
from .utils import (
    dedupe_display,
    display_keyphrase,
    normalize_phrase,
    strong_candidate_concept,
    token_overlap_score,
)


def map_to_taxonomy(
    keyphrases: Sequence[str],
    names: Sequence[str],
    taxonomy: ProjectTaxonomy,
    semantic_ranker: SemanticKeyphraseRanker,
    source_text: str,
) -> list[TaxonomyMatch]:
    terms = dedupe_display([*keyphrases, *names])
    items = taxonomy_items(taxonomy)
    matches: dict[tuple[KnowledgeConceptKind, str], TaxonomyMatch] = {}
    semantic_candidates = [item.canonical for item in items]
    semantic_scores = semantic_ranker.rank(source_text, semantic_candidates)

    for item in items:
        item_terms = set(tokenize_text(item.canonical))
        item_normalized = normalize_phrase(item.canonical)
        for term in terms:
            term_normalized = normalize_phrase(term)
            if not term_normalized:
                continue
            confidence = 0.0
            source = ""
            needs_review = False
            if term_normalized == item_normalized:
                confidence = 0.94
                source = "taxonomy-exact"
            elif term_normalized in {normalize_phrase(alias) for alias in item.aliases}:
                confidence = 0.91
                source = "taxonomy-alias"
            else:
                overlap = token_overlap_score(set(term_normalized.split()), item_terms)
                semantic = semantic_scores.get(item.canonical, 0.0)
                if overlap >= 0.5:
                    confidence = 0.76
                    source = "taxonomy-token-overlap"
                elif semantic >= 0.45:
                    confidence = 0.68
                    source = "taxonomy-semantic-similarity"

            if confidence == 0.0:
                continue
            if (
                item.bootstrap_status
                and item.bootstrap_status != ProjectTaxonomyBootstrapStatus.SELECTED
            ):
                confidence = min(confidence, 0.48)
                source = f"bootstrap-{item.bootstrap_status}"
                needs_review = True
            match = TaxonomyMatch(
                kind=item.kind,
                canonical=item.canonical,
                confidence=confidence,
                source=source,
                needs_review=needs_review,
            )
            key = (match.kind, match.canonical)
            if key not in matches or matches[key].confidence < match.confidence:
                matches[key] = match

    for term in terms[:8]:
        normalized = normalize_phrase(term)
        if not normalized:
            continue
        if any(match.canonical == term for match in matches.values()):
            continue
        if normalized.replace(" ", "-") in BOOTSTRAP_HINTS:
            matches.setdefault(
                (KnowledgeConceptKind.CANDIDATE, term),
                TaxonomyMatch(
                    kind=KnowledgeConceptKind.CANDIDATE,
                    canonical=display_keyphrase(term),
                    confidence=0.42,
                    source="bootstrap-candidate",
                    needs_review=True,
                ),
            )
        elif strong_candidate_concept(term):
            matches.setdefault(
                (KnowledgeConceptKind.CANDIDATE, term),
                TaxonomyMatch(
                    kind=KnowledgeConceptKind.CANDIDATE,
                    canonical=display_keyphrase(term),
                    confidence=0.46,
                    source="unmatched-strong-candidate",
                    needs_review=True,
                ),
            )
    return sorted(matches.values(), key=lambda item: (-item.confidence, item.kind, item.canonical))


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
