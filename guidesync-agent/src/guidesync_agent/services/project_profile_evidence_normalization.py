from __future__ import annotations

import re
from dataclasses import dataclass, field

from guidesync_agent.schemas import (
    ProjectProfileAgentEvidence,
    ProjectProfileAgentOutput,
    ProjectProfileEvidenceRef,
    ProjectTaxonomy,
    ProjectTaxonomyEvidenceKind,
    ProjectTaxonomyEvidenceRef,
)


@dataclass
class ProjectProfileEvidenceIndex:
    refs_by_path: dict[str, set[str]] = field(default_factory=dict)
    paths_by_ref: dict[str, tuple[str, str]] = field(default_factory=dict)
    text_by_ref: dict[str, list[str]] = field(default_factory=dict)

    @property
    def allowed_refs(self) -> set[str]:
        return set(self.paths_by_ref)


def canonicalize_project_profile_output(
    output: ProjectProfileAgentOutput,
    evidence: ProjectProfileAgentEvidence,
) -> ProjectProfileAgentOutput:
    index = build_evidence_index(evidence)
    profile_evidence = [
        canonicalize_profile_evidence_ref(ref, index) for ref in output.profile_evidence
    ]
    return output.model_copy(
        update={
            "profile_evidence": profile_evidence,
            "taxonomy": canonicalize_taxonomy_evidence(
                output.taxonomy,
                index,
                fallback_refs=refs_from_profile_evidence(profile_evidence, index),
            ),
        }
    )


def build_evidence_index(evidence: ProjectProfileAgentEvidence) -> ProjectProfileEvidenceIndex:
    index = ProjectProfileEvidenceIndex()
    for listing in evidence.file_listings:
        for file_ref in listing.files:
            add_path_ref(index, file_ref.repository_id, file_ref.path, file_ref.evidence_ref)
    for window in evidence.file_windows:
        source = repository_evidence_ref(window.repository_id, window.path)
        add_path_ref(index, window.repository_id, window.path, source)
        if window.content:
            index.text_by_ref.setdefault(source, []).append(window.content)
    for result in evidence.search_results:
        for match in result.matches:
            source = repository_evidence_ref(match.repository_id, match.path)
            add_path_ref(index, match.repository_id, match.path, source)
            index.text_by_ref.setdefault(source, []).append(match.preview)
    return index


def add_path_ref(
    index: ProjectProfileEvidenceIndex,
    repository_id: str,
    path: str,
    source: str,
) -> None:
    normalized = normalize_path(path)
    index.refs_by_path.setdefault(normalized, set()).add(source)
    index.paths_by_ref[source] = (repository_id, path)


def canonicalize_profile_evidence_ref(
    ref: ProjectProfileEvidenceRef,
    index: ProjectProfileEvidenceIndex,
) -> ProjectProfileEvidenceRef:
    source = canonical_repository_ref(ref.path, ref.repository_id, index)
    if not source:
        return ref
    repository_id, path = index.paths_by_ref[source]
    return ref.model_copy(update={"repository_id": repository_id, "path": path})


def canonicalize_taxonomy_evidence(
    taxonomy: ProjectTaxonomy,
    index: ProjectProfileEvidenceIndex,
    *,
    fallback_refs: list[str],
) -> ProjectTaxonomy:
    evidence_by_key = {
        (item.kind, normalize_text(item.value)): canonicalize_taxonomy_ref_item(item, index)
        for item in taxonomy.evidence_refs
    }
    for kind, value in required_taxonomy_values(taxonomy):
        key = (kind, normalize_text(value))
        item = evidence_by_key.get(key)
        if item is None:
            inferred_refs = inferred_refs_for_value(value, index) or fallback_refs
            if inferred_refs:
                evidence_by_key[key] = ProjectTaxonomyEvidenceRef(
                    kind=kind,
                    value=value,
                    reason="Inferred from inspected repository evidence.",
                    evidence_refs=inferred_refs,
                )
            continue
        if not item.evidence_refs:
            inferred_refs = inferred_refs_for_value(value, index) or fallback_refs
            if inferred_refs:
                evidence_by_key[key] = item.model_copy(
                    update={"evidence_refs": inferred_refs}
                )
    return taxonomy.model_copy(update={"evidence_refs": list(evidence_by_key.values())})


def refs_from_profile_evidence(
    profile_evidence: list[ProjectProfileEvidenceRef],
    index: ProjectProfileEvidenceIndex,
) -> list[str]:
    refs = []
    for ref in profile_evidence:
        source = canonical_repository_ref(ref.path, ref.repository_id, index)
        if source:
            refs.append(source)
    return unique_values(refs)


def canonicalize_taxonomy_ref_item(
    item: ProjectTaxonomyEvidenceRef,
    index: ProjectProfileEvidenceIndex,
) -> ProjectTaxonomyEvidenceRef:
    refs = []
    for raw_ref in item.evidence_refs:
        source = canonical_repository_ref(raw_ref, None, index)
        if source:
            refs.append(source)
    return item.model_copy(update={"evidence_refs": unique_values(refs)})


def required_taxonomy_values(
    taxonomy: ProjectTaxonomy,
) -> list[tuple[ProjectTaxonomyEvidenceKind, str]]:
    values = [(ProjectTaxonomyEvidenceKind.CATEGORY, value) for value in taxonomy.categories]
    values.extend((ProjectTaxonomyEvidenceKind.COMPONENT, value) for value in taxonomy.components)
    values.extend((ProjectTaxonomyEvidenceKind.WORKFLOW, value) for value in taxonomy.workflows)
    values.extend(
        (ProjectTaxonomyEvidenceKind.DOCUMENTATION_AREA, value)
        for value in taxonomy.documentation_areas
    )
    values.extend(
        (ProjectTaxonomyEvidenceKind.DOMAIN_TERM, value) for value in taxonomy.domain_terms
    )
    return values


def inferred_refs_for_value(
    value: str,
    index: ProjectProfileEvidenceIndex,
) -> list[str]:
    normalized_value = normalize_text(value)
    refs = []
    for path, path_refs in index.refs_by_path.items():
        if path and path in normalized_value:
            refs.extend(sorted(path_refs))
    if refs:
        return unique_values(refs)
    for source, text_parts in index.text_by_ref.items():
        searchable_text = normalize_text("\n".join(text_parts))
        if normalized_value and normalized_value in searchable_text:
            refs.append(source)
    return unique_values(refs)


def canonical_repository_ref(
    value: str,
    repository_id: str | None,
    index: ProjectProfileEvidenceIndex,
) -> str | None:
    if value in index.allowed_refs:
        return value
    if repository_id:
        source = repository_evidence_ref(repository_id, value)
        if source in index.allowed_refs:
            return source
    parsed = parse_repository_evidence_ref(value)
    if parsed:
        source = repository_evidence_ref(parsed[0], parsed[1])
        if source in index.allowed_refs:
            return source
    refs = index.refs_by_path.get(normalize_path(value), set())
    return next(iter(refs)) if len(refs) == 1 else None


def parse_repository_evidence_ref(value: str) -> tuple[str, str] | None:
    if not value.startswith("repo:"):
        return None
    parts = value.split(":", 2)
    if len(parts) != 3:
        return None
    _, repository_id, path = parts
    return repository_id, path


def repository_evidence_ref(repository_id: str, path: str) -> str:
    return f"repo:{repository_id}:{path}"


def normalize_path(value: str) -> str:
    return value.strip().replace("\\", "/").removeprefix("./").lower()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def unique_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
