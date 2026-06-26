from __future__ import annotations

from collections import Counter

from guidesync_agent.knowledge_tagging import tokenize_text
from guidesync_agent.schemas import ProjectConfig, ProjectProfileRepositoryMapItem

from .project_profile_sources import ProfileDocuments

ARCHITECTURE_TERMS = {
    "architecture",
    "component",
    "components",
    "design",
    "pipeline",
    "service",
    "system",
}
WORKFLOW_TERMS = {
    "deploy",
    "deployment",
    "guide",
    "run",
    "setup",
    "test",
    "usage",
    "workflow",
}
STOP_TERMS = {
    "about",
    "after",
    "and",
    "are",
    "before",
    "from",
    "guide",
    "into",
    "not",
    "project",
    "that",
    "the",
    "this",
    "with",
}


def summarize_project(project: ProjectConfig, docs: ProfileDocuments) -> str:
    base = project.description or (
        f"{project.name} is configured for {project.audience.value.replace('_', ' ')} "
        "documentation updates."
    )
    docs_summary = (
        f" The baseline profile scanned {len(docs.files)} project files"
        f" and read {len(docs.text_files)} bounded text files."
        if docs.files
        else " The baseline profile did not find readable project files yet."
    )
    return f"{base.strip()}{docs_summary}"


def summarize_architecture(
    project: ProjectConfig,
    repository_map: list[ProjectProfileRepositoryMapItem],
    docs: ProfileDocuments,
) -> list[str]:
    architecture = filtered_headings(docs.headings, ARCHITECTURE_TERMS)
    if architecture:
        return architecture[:8]
    repositories = ", ".join(item.name for item in repository_map) or "no repositories"
    analysis_paths = ", ".join(project.analysis_paths) or "repository defaults"
    return [
        f"Repositories: {repositories}.",
        f"Knowledge base path: {project.knowledge_base_path or 'repository root'}.",
        f"Analysis paths: {analysis_paths}.",
    ]


def summarize_workflows(project: ProjectConfig, docs: ProfileDocuments) -> list[str]:
    workflows = filtered_headings(docs.headings, WORKFLOW_TERMS)
    if workflows:
        return workflows[:8]
    if project.documentation_instructions:
        return [project.documentation_instructions]
    return [
        "Documentation update runs should start from repository evidence "
        "and saved project settings."
    ]


def filtered_headings(headings: list[str], terms: set[str]) -> list[str]:
    matches = []
    seen: set[str] = set()
    for heading in headings:
        normalized = heading.lower()
        if normalized in seen:
            continue
        if any(term in tokenize_text(heading) or term in normalized for term in terms):
            matches.append(heading)
            seen.add(normalized)
    return matches


def extract_key_terms(
    project: ProjectConfig,
    docs: ProfileDocuments,
    repository_map: list[ProjectProfileRepositoryMapItem],
) -> list[str]:
    text = " ".join(
        [
            project.name,
            project.description or "",
            project.documentation_instructions,
            " ".join(docs.headings),
            " ".join(docs.files),
            " ".join(sample.excerpt for sample in docs.text_samples),
            " ".join(" ".join(sample.symbols) for sample in docs.text_samples),
            " ".join(" ".join(sample.key_terms) for sample in docs.text_samples),
            " ".join(repository.name for repository in repository_map),
        ]
    )
    counts = Counter(
        term for term in tokenize_text(text) if term not in STOP_TERMS and len(term) > 2
    )
    return [term for term, _ in counts.most_common(16)]


def uncertainty_notes_for(
    project: ProjectConfig,
    docs: ProfileDocuments,
    warnings: list[str],
) -> list[str]:
    notes = [
        "Profile is generated from saved project settings and bounded locally cached "
        "project files.",
    ]
    if warnings:
        notes.append(
            "Some source evidence was unavailable; see warnings before relying on this profile."
        )
    if not project.description:
        notes.append(
            "Project description is empty, so summary quality depends on repository documentation."
        )
    if not docs.text_files:
        notes.append(
            "No bounded text files were readable for taxonomy extraction; path evidence was used."
        )
    elif not docs.headings:
        notes.append(
            "No documentation headings were available for architecture/workflow extraction."
        )
    return notes
