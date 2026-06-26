from __future__ import annotations

import re
from pathlib import Path

from guidesync_agent.knowledge_tagging import tokenize_text
from guidesync_agent.schemas import (
    ProjectConfig,
    ProjectProfileRepositoryMapItem,
    ProjectTaxonomy,
    ProjectTaxonomyAlias,
    ProjectTaxonomyAudienceTerm,
    ProjectTaxonomyBootstrapHint,
    ProjectTaxonomyBootstrapStatus,
    ProjectTaxonomyCandidateKind,
    ProjectTaxonomyCandidateTerm,
)

from .project_profile_sources import ProfileDocuments

DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
BOOTSTRAP_CATEGORY_HINTS = [
    "billing",
    "auth",
    "user-management",
    "workspace",
    "settings",
    "api",
    "ui-workflow",
    "release-notes",
    "docs",
]
TAXONOMY_CATEGORY_RULES = {
    "api": {"api", "endpoint", "route", "router", "controller", "request", "response"},
    "auth": {"auth", "credential", "login", "oauth", "permission", "token", "user"},
    "documentation-workflow": {
        "doc",
        "docs",
        "documentation",
        "guide",
        "markdown",
        "release",
        "update",
    },
    "docs": {"doc", "docs", "documentation", "guide", "readme"},
    "knowledge-base": {
        "annotation",
        "concept",
        "embedding",
        "knowledge",
        "retrieval",
        "search",
        "taxonomy",
    },
    "model-configuration": {
        "llm",
        "model",
        "profile",
        "provider",
        "prompt",
        "setting",
    },
    "repository-management": {"branch", "cache", "commit", "git", "repository", "repo"},
    "release-notes": {"changelog", "release", "releases", "notes"},
    "settings": {"config", "configuration", "env", "setting", "settings"},
    "ui-workflow": {"component", "frontend", "page", "screen", "tsx", "ui", "view"},
    "workspace": {"project", "workspace"},
}


def build_project_taxonomy(
    project: ProjectConfig,
    docs: ProfileDocuments,
    repository_map: list[ProjectProfileRepositoryMapItem],
    architecture: list[str],
    workflows: list[str],
    key_terms: list[str],
    *,
    taxonomy_version: str,
) -> ProjectTaxonomy:
    evidence_text = " ".join(
        [
            project.name,
            project.description or "",
            project.documentation_instructions,
            " ".join(docs.files),
            " ".join(docs.headings),
            " ".join(architecture),
            " ".join(workflows),
            " ".join(key_terms),
            " ".join(repository.name for repository in repository_map),
        ]
    )
    categories = taxonomy_categories(evidence_text)
    components = taxonomy_components(docs, repository_map)
    documentation_areas = taxonomy_documentation_areas(docs)
    domain_terms = taxonomy_domain_terms(project, docs, key_terms)
    aliases = taxonomy_aliases(domain_terms, categories)
    bootstrap_hints = taxonomy_bootstrap_hints(categories, evidence_text, docs)
    candidate_terms = taxonomy_candidate_terms(
        key_terms,
        domain_terms,
        categories,
        components,
        documentation_areas,
        docs,
    )
    return ProjectTaxonomy(
        version=taxonomy_version,
        categories=categories,
        components=components,
        workflows=unique_terms(workflows)[:12],
        documentation_areas=documentation_areas,
        domain_terms=domain_terms,
        aliases=aliases,
        audience_terms=taxonomy_audience_terms(project),
        bootstrap_hints=bootstrap_hints,
        candidate_terms=candidate_terms,
        uncertainty_notes=[
            "Taxonomy is generated from bounded project-profile evidence and should be "
            "reviewed when repository evidence is incomplete."
        ],
    )


def taxonomy_categories(evidence_text: str) -> list[str]:
    tokens = set(tokenize_text(evidence_text))
    categories = [
        category
        for category, terms in TAXONOMY_CATEGORY_RULES.items()
        if tokens & terms or set(category.split("-")) <= tokens
    ]
    return unique_terms(categories)[:12]


def taxonomy_components(
    docs: ProfileDocuments,
    repository_map: list[ProjectProfileRepositoryMapItem],
) -> list[str]:
    candidates: list[str] = []
    candidates.extend(repository.name for repository in repository_map)
    candidates.extend(component_names_from_paths(docs.files))
    candidates.extend(component_names_from_headings(docs.headings))
    return unique_terms(candidates)[:24]


def taxonomy_documentation_areas(docs: ProfileDocuments) -> list[str]:
    areas: list[str] = []
    for path in docs.files:
        if Path(path).suffix.lower() not in DOC_SUFFIXES:
            continue
        stem = display_phrase(Path(path).stem)
        if stem:
            areas.append(stem)
    for heading in docs.headings:
        normalized = set(tokenize_text(heading))
        if normalized & {"admin", "guide", "readme", "release", "setup", "usage"}:
            areas.append(display_phrase(heading))
    return unique_terms(areas)[:16]


def taxonomy_domain_terms(
    project: ProjectConfig,
    docs: ProfileDocuments,
    key_terms: list[str],
) -> list[str]:
    terms = [display_phrase(term) for term in key_terms]
    for heading in docs.headings:
        tokens = tokenize_text(heading)
        if 1 < len(tokens) <= 4:
            terms.append(" ".join(tokens))
    project_tokens = tokenize_text(project.name)
    if 1 < len(project_tokens) <= 4:
        terms.append(" ".join(project_tokens))
    return unique_terms(terms)[:24]


def taxonomy_aliases(
    domain_terms: list[str],
    categories: list[str],
) -> list[ProjectTaxonomyAlias]:
    normalized_terms = {normalize_phrase(term) for term in [*domain_terms, *categories]}
    aliases: list[ProjectTaxonomyAlias] = []
    if "knowledge base" in normalized_terms or "knowledge" in normalized_terms:
        aliases.append(
            ProjectTaxonomyAlias(
                canonical="knowledge base",
                aliases=["KB", "documentation corpus", "knowledge corpus"],
            )
        )
    if "release note" in normalized_terms or "release-notes" in categories:
        aliases.append(
            ProjectTaxonomyAlias(
                canonical="release notes",
                aliases=["changelog", "release summary"],
            )
        )
    if "model profile" in normalized_terms or "model-configuration" in categories:
        aliases.append(
            ProjectTaxonomyAlias(
                canonical="model profile",
                aliases=["model settings", "provider profile"],
            )
        )
    return aliases


def taxonomy_bootstrap_hints(
    categories: list[str],
    evidence_text: str,
    docs: ProfileDocuments,
) -> list[ProjectTaxonomyBootstrapHint]:
    tokens = set(tokenize_text(evidence_text))
    hints: list[ProjectTaxonomyBootstrapHint] = []
    for hint in BOOTSTRAP_CATEGORY_HINTS:
        hint_tokens = set(tokenize_text(hint))
        matching_paths = [
            ref.path
            for ref in docs.evidence_refs[:80]
            if hint_tokens and hint_tokens <= set(tokenize_text(ref.path))
        ]
        if hint in categories:
            status = ProjectTaxonomyBootstrapStatus.SELECTED
            reason = "selected by project-profile taxonomy category evidence"
        elif hint_tokens and (hint_tokens <= tokens or matching_paths):
            status = ProjectTaxonomyBootstrapStatus.CANDIDATE
            reason = "seen in bounded profile evidence but not promoted to controlled category"
        else:
            status = ProjectTaxonomyBootstrapStatus.REJECTED
            reason = "not visible in bounded profile evidence"
        hints.append(
            ProjectTaxonomyBootstrapHint(
                value=hint,
                status=status,
                reason=reason,
                evidence_refs=matching_paths[:5],
            )
        )
    return hints


def taxonomy_candidate_terms(
    key_terms: list[str],
    domain_terms: list[str],
    categories: list[str],
    components: list[str],
    documentation_areas: list[str],
    docs: ProfileDocuments,
) -> list[ProjectTaxonomyCandidateTerm]:
    controlled = {
        normalize_phrase(term)
        for term in [*domain_terms, *categories, *components, *documentation_areas]
    }
    candidates: list[ProjectTaxonomyCandidateTerm] = []
    for term in key_terms:
        normalized = normalize_phrase(term)
        if not normalized or normalized in controlled:
            continue
        evidence_refs = [
            ref.path for ref in docs.evidence_refs[:80] if normalized in normalize_phrase(ref.path)
        ][:5]
        candidates.append(
            ProjectTaxonomyCandidateTerm(
                value=term,
                kind=ProjectTaxonomyCandidateKind.DOMAIN_TERM,
                reason="frequent project-profile term not promoted to controlled taxonomy",
                evidence_refs=evidence_refs,
            )
        )
    return candidates[:12]


def taxonomy_audience_terms(project: ProjectConfig) -> list[ProjectTaxonomyAudienceTerm]:
    audience_value = project.audience.value
    if audience_value == "developers":
        return [
            ProjectTaxonomyAudienceTerm(
                audience=project.audience,
                preferred=["API", "component", "repository", "configuration"],
                avoid=["magic", "just works"],
            )
        ]
    if audience_value == "business_analysts":
        return [
            ProjectTaxonomyAudienceTerm(
                audience=project.audience,
                preferred=["workflow", "report", "release note"],
                avoid=["internal implementation detail"],
            )
        ]
    return [
        ProjectTaxonomyAudienceTerm(
            audience=project.audience,
            preferred=["workspace", "settings", "guide"],
            avoid=["tenant", "implementation detail"],
        )
    ]


def component_names_from_paths(paths: list[str]) -> list[str]:
    names: list[str] = []
    for path in paths:
        stem = Path(path).stem
        if not stem or stem in {"index", "__init__"}:
            continue
        if any(part[0].isupper() for part in re.findall(r"[A-Za-z][A-Za-z0-9]*", stem)):
            names.append(stem)
            continue
        tokens = tokenize_text(stem)
        if 1 <= len(tokens) <= 4:
            names.append(" ".join(tokens))
    return names


def component_names_from_headings(headings: list[str]) -> list[str]:
    names: list[str] = []
    for heading in headings:
        if re.search(r"\b[A-Z][A-Za-z0-9]+(?:[A-Z][a-z0-9]+)[A-Za-z0-9]*\b", heading):
            names.append(heading)
    return names


def display_phrase(value: str) -> str:
    tokens = tokenize_text(value)
    return " ".join(tokens) if tokens else value.strip()


def normalize_phrase(value: str) -> str:
    return " ".join(tokenize_text(value))


def unique_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        result.append(cleaned)
        seen.add(key)
    return result
