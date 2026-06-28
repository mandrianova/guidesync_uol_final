from __future__ import annotations

from guidesync_agent.schemas import (
    CodeChangeAnalysis,
    CodeChangeCandidateTaxonomyUpdate,
    CodeChangeEvidenceRef,
    CodeChangeTaxonomyMatch,
    KnowledgeConceptKind,
    ProjectTaxonomy,
    ValidationFinding,
)


def sanitize_taxonomy_matches(
    analysis: CodeChangeAnalysis,
    taxonomy: ProjectTaxonomy | None,
) -> tuple[CodeChangeAnalysis, list[ValidationFinding]]:
    if taxonomy is None:
        return analysis, []
    controlled = controlled_taxonomy_values(taxonomy)
    valid_matches: list[CodeChangeTaxonomyMatch] = []
    candidate_updates = [*analysis.candidate_taxonomy_updates]
    findings: list[ValidationFinding] = []
    for match in analysis.taxonomy_matches:
        if normalize(match.value) in controlled.get(match.kind, set()):
            valid_matches.append(match)
            continue
        candidate_updates.append(
            CodeChangeCandidateTaxonomyUpdate(
                kind=match.kind,
                value=match.value,
                reason="Model suggested a taxonomy match outside the project profile taxonomy.",
                evidence_refs=match.evidence_refs,
            )
        )
        findings.append(
            ValidationFinding(
                severity="warning",
                check="code-change-analysis.taxonomy",
                message=(
                    f"`{match.value}` is not a controlled {match.kind.value}; kept as candidate."
                ),
                evidence_refs=match.evidence_refs,
            )
        )
    return analysis.model_copy(
        update={
            "taxonomy_matches": valid_matches,
            "candidate_taxonomy_updates": dedupe_candidate_updates(candidate_updates),
        }
    ), findings


def controlled_taxonomy_values(
    taxonomy: ProjectTaxonomy,
) -> dict[KnowledgeConceptKind, set[str]]:
    return {
        KnowledgeConceptKind.CATEGORY: normalized_values(taxonomy.categories),
        KnowledgeConceptKind.COMPONENT: normalized_values(taxonomy.components),
        KnowledgeConceptKind.WORKFLOW: normalized_values(taxonomy.workflows),
        KnowledgeConceptKind.DOCUMENTATION_AREA: normalized_values(taxonomy.documentation_areas),
        KnowledgeConceptKind.DOMAIN_TERM: normalized_values(taxonomy.domain_terms),
    }


def taxonomy_matches_for_terms(
    terms: list[str],
    taxonomy: ProjectTaxonomy | None,
    evidence_refs: list[CodeChangeEvidenceRef],
) -> list[CodeChangeTaxonomyMatch]:
    if taxonomy is None:
        return []
    controlled = controlled_taxonomy_values(taxonomy)
    refs = [ref.source for ref in evidence_refs]
    matches: list[CodeChangeTaxonomyMatch] = []
    for kind, values in controlled.items():
        for term in terms:
            normalized = normalize(term)
            if normalized in values:
                matches.append(
                    CodeChangeTaxonomyMatch(
                        kind=kind,
                        value=canonical_taxonomy_value(kind, term, taxonomy),
                        confidence=0.7,
                        evidence_refs=refs,
                    )
                )
    return dedupe_taxonomy_matches(matches)


def candidate_terms_for_terms(
    terms: list[str],
    taxonomy: ProjectTaxonomy | None,
    evidence_refs: list[CodeChangeEvidenceRef],
) -> list[CodeChangeCandidateTaxonomyUpdate]:
    controlled = set().union(*controlled_taxonomy_values(taxonomy).values()) if taxonomy else set()
    refs = [ref.source for ref in evidence_refs]
    return [
        CodeChangeCandidateTaxonomyUpdate(
            kind=KnowledgeConceptKind.CANDIDATE,
            value=term,
            reason="Code term was not present in the project-profile taxonomy.",
            evidence_refs=refs,
        )
        for term in terms[:6]
        if normalize(term) not in controlled
    ]


def canonical_taxonomy_value(
    kind: KnowledgeConceptKind,
    value: str,
    taxonomy: ProjectTaxonomy,
) -> str:
    candidates = {
        KnowledgeConceptKind.CATEGORY: taxonomy.categories,
        KnowledgeConceptKind.COMPONENT: taxonomy.components,
        KnowledgeConceptKind.WORKFLOW: taxonomy.workflows,
        KnowledgeConceptKind.DOCUMENTATION_AREA: taxonomy.documentation_areas,
        KnowledgeConceptKind.DOMAIN_TERM: taxonomy.domain_terms,
    }.get(kind, [])
    normalized = normalize(value)
    return next(
        (candidate for candidate in candidates if normalize(candidate) == normalized),
        value,
    )


def values_for_kind(
    matches: list[CodeChangeTaxonomyMatch],
    kind: KnowledgeConceptKind,
) -> list[str]:
    return dedupe_preserve_order([match.value for match in matches if match.kind == kind])


def dedupe_taxonomy_matches(
    matches: list[CodeChangeTaxonomyMatch],
) -> list[CodeChangeTaxonomyMatch]:
    seen: set[tuple[KnowledgeConceptKind, str]] = set()
    result: list[CodeChangeTaxonomyMatch] = []
    for match in matches:
        key = (match.kind, normalize(match.value))
        if key in seen:
            continue
        seen.add(key)
        result.append(match)
    return result


def dedupe_candidate_updates(
    updates: list[CodeChangeCandidateTaxonomyUpdate],
) -> list[CodeChangeCandidateTaxonomyUpdate]:
    seen: set[tuple[KnowledgeConceptKind, str]] = set()
    result: list[CodeChangeCandidateTaxonomyUpdate] = []
    for update in updates:
        key = (update.kind, normalize(update.value))
        if key in seen:
            continue
        seen.add(key)
        result.append(update)
    return result


def normalized_values(values: list[str]) -> set[str]:
    return {normalize(value) for value in values}


def normalize(value: str) -> str:
    return " ".join(value.lower().replace("_", " ").replace("-", " ").split())


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = normalize(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result
