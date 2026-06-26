from __future__ import annotations

from guidesync_agent.knowledge_tagging import tokenize_text
from guidesync_agent.schemas import (
    ProjectTaxonomyAlias,
    ProjectTaxonomyBootstrapHint,
    ProjectTaxonomyEvidenceKind,
    ProjectTaxonomyEvidenceRef,
)

from .project_profile_sources import ProfileDocuments


def taxonomy_evidence_refs(
    *,
    categories: list[str],
    components: list[str],
    workflows: list[str],
    documentation_areas: list[str],
    domain_terms: list[str],
    aliases: list[ProjectTaxonomyAlias],
    bootstrap_hints: list[ProjectTaxonomyBootstrapHint],
    docs: ProfileDocuments,
) -> list[ProjectTaxonomyEvidenceRef]:
    evidence: list[ProjectTaxonomyEvidenceRef] = []
    evidence.extend(evidence_for_values(categories, ProjectTaxonomyEvidenceKind.CATEGORY, docs))
    evidence.extend(evidence_for_values(components, ProjectTaxonomyEvidenceKind.COMPONENT, docs))
    evidence.extend(evidence_for_values(workflows, ProjectTaxonomyEvidenceKind.WORKFLOW, docs))
    evidence.extend(
        evidence_for_values(
            documentation_areas,
            ProjectTaxonomyEvidenceKind.DOCUMENTATION_AREA,
            docs,
        )
    )
    evidence.extend(
        evidence_for_values(domain_terms, ProjectTaxonomyEvidenceKind.DOMAIN_TERM, docs)
    )
    for alias in aliases:
        refs = evidence_refs_for_value(alias.canonical, docs)
        evidence.append(
            ProjectTaxonomyEvidenceRef(
                value=alias.canonical,
                kind=ProjectTaxonomyEvidenceKind.ALIAS,
                reason="Alias canonical term appeared in bounded project-profile evidence.",
                evidence_refs=refs,
            )
        )
    for hint in bootstrap_hints:
        refs = evidence_refs_for_value(hint.value, docs)
        evidence.append(
            ProjectTaxonomyEvidenceRef(
                value=hint.value,
                kind=ProjectTaxonomyEvidenceKind.BOOTSTRAP_HINT,
                reason=hint.reason,
                evidence_refs=refs or hint.evidence_refs,
            )
        )
    return [item for item in evidence if item.evidence_refs][:80]


def taxonomy_confidence(
    docs: ProfileDocuments,
    evidence: list[ProjectTaxonomyEvidenceRef],
) -> float:
    score = 0.35
    if docs.files:
        score += 0.15
    if docs.text_samples:
        score += 0.2
    if evidence:
        score += min(len(evidence) * 0.015, 0.2)
    if docs.warnings:
        score -= min(len(docs.warnings) * 0.03, 0.15)
    return max(0.0, min(score, 0.95))


def evidence_for_values(
    values: list[str],
    kind: ProjectTaxonomyEvidenceKind,
    docs: ProfileDocuments,
) -> list[ProjectTaxonomyEvidenceRef]:
    return [
        ProjectTaxonomyEvidenceRef(
            value=value,
            kind=kind,
            reason=f"{kind.value} appeared in bounded project-profile evidence.",
            evidence_refs=refs,
        )
        for value in values
        if (refs := evidence_refs_for_value(value, docs))
    ]


def evidence_refs_for_value(value: str, docs: ProfileDocuments) -> list[str]:
    tokens = set(tokenize_text(value))
    if not tokens:
        return []
    refs: list[str] = []
    for ref in docs.evidence_refs:
        if tokens & set(tokenize_text(ref.path)):
            refs.append(ref.path)
    for sample in docs.text_samples:
        sample_text = " ".join(
            [
                sample.path,
                " ".join(sample.headings),
                " ".join(sample.symbols),
                " ".join(sample.key_terms),
                sample.excerpt,
            ]
        )
        if tokens & set(tokenize_text(sample_text)):
            refs.append(sample.path)
    return dedupe(refs)[:8]


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
