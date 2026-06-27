from __future__ import annotations

import json
import os
from pathlib import Path

from guidesync_agent.prompts.loader import load_prompt_file
from guidesync_agent.schemas import (
    ProjectConfig,
    ProjectProfileEvidenceRef,
    ProjectProfileRepositoryMapItem,
    ProjectProfileSnapshot,
    ProjectTaxonomy,
)


def write_project_profile_artifacts(
    project: ProjectConfig,
    profile: ProjectProfileSnapshot,
) -> ProjectProfileSnapshot:
    output_dir = project_profile_output_dir() / project.id / profile.id
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "profile.json"
    markdown_path = output_dir / "profile.md"
    profile_with_artifacts = profile.model_copy(
        update={
            "artifact_uris": {
                "profile.json": str(json_path),
                "profile.md": str(markdown_path),
            }
        }
    )
    json_path.write_text(
        json.dumps(profile_with_artifacts.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        project_profile_markdown(project, profile_with_artifacts),
        encoding="utf-8",
    )
    return profile_with_artifacts


def project_profile_output_dir() -> Path:
    return Path(os.environ.get("GUIDESYNC_PROJECT_PROFILE_OUTPUT_DIR", "outputs/project-profiles"))


def project_profile_markdown(project: ProjectConfig, profile: ProjectProfileSnapshot) -> str:
    prompt = load_prompt_file("project_profile/analyzer.md", version=profile.prompt_version)
    sections = [
        f"# Project Profile: {project.name}",
        f"Profile id: `{profile.id}`",
        f"Version: `{profile.version}`",
        f"Prompt version: `{profile.prompt_version}`",
        f"Prompt SHA256: `{prompt.sha256}`",
        f"Prompt path: `{prompt.path}`",
        "",
        "## Summary",
        profile.summary,
        "",
        markdown_list("Architecture", profile.architecture),
        markdown_list("Workflows", profile.workflows),
        markdown_list("Key terms", profile.key_terms),
        markdown_taxonomy(profile.taxonomy),
        markdown_profile_evidence(profile.profile_evidence),
        markdown_repository_map(profile.repository_map),
        markdown_model_metadata(profile),
        markdown_list("Warnings", profile.warnings),
        markdown_list("Uncertainty notes", profile.uncertainty_notes),
    ]
    return "\n".join(sections).rstrip() + "\n"


def markdown_list(title: str, items: list[str]) -> str:
    lines = [f"## {title}"]
    lines.extend(f"- {item}" for item in items)
    if len(lines) == 1:
        lines.append("- None recorded.")
    return "\n".join(lines)


def markdown_repository_map(repository_map: list[ProjectProfileRepositoryMapItem]) -> str:
    lines = ["## Repository map"]
    if not repository_map:
        lines.append("- None configured.")
        return "\n".join(lines)
    for repository in repository_map:
        commit = repository.current_commit or "unknown commit"
        lines.append(
            f"- `{repository.repository_id}` {repository.name}: "
            f"{repository.default_branch or 'default ref'} at {commit}"
        )
    return "\n".join(lines)


def markdown_taxonomy(taxonomy: ProjectTaxonomy) -> str:
    sections = [
        "## Controlled taxonomy",
        f"- Version: `{taxonomy.version or 'unversioned'}`",
        f"- Confidence: `{taxonomy.confidence:.2f}`",
        markdown_list("Categories", taxonomy.categories),
        markdown_list("Components", taxonomy.components),
        markdown_list("Taxonomy workflows", taxonomy.workflows),
        markdown_list("Documentation areas", taxonomy.documentation_areas),
        markdown_list("Domain terms", taxonomy.domain_terms),
    ]
    if taxonomy.aliases:
        sections.append("### Aliases")
        sections.extend(
            f"- {alias.canonical}: {', '.join(alias.aliases) or 'None'}"
            for alias in taxonomy.aliases
        )
    if taxonomy.bootstrap_hints:
        sections.append("### Bootstrap hints")
        sections.extend(
            f"- {hint.value}: {hint.status} - {hint.reason}" for hint in taxonomy.bootstrap_hints
        )
    if taxonomy.candidate_terms:
        sections.append("### Candidate terms")
        sections.extend(
            f"- {candidate.value} ({candidate.kind}): {candidate.reason}"
            for candidate in taxonomy.candidate_terms
        )
    if taxonomy.evidence_refs:
        sections.append("### Taxonomy evidence")
        sections.extend(
            f"- {evidence.kind} `{evidence.value}`: {', '.join(evidence.evidence_refs)}"
            for evidence in taxonomy.evidence_refs[:30]
        )
    return "\n".join(sections)


def markdown_profile_evidence(evidence_refs: list[ProjectProfileEvidenceRef]) -> str:
    lines = ["## Profile evidence"]
    if not evidence_refs:
        lines.append("- None recorded.")
        return "\n".join(lines)
    for evidence in evidence_refs[:40]:
        repository = f" `{evidence.repository_id}`" if evidence.repository_id else ""
        lines.append(f"-{repository} `{evidence.path}`: {evidence.reason}")
    if len(evidence_refs) > 40:
        lines.append(f"- ... {len(evidence_refs) - 40} more evidence refs")
    return "\n".join(lines)


def markdown_model_metadata(profile: ProjectProfileSnapshot) -> str:
    lines = ["## Agent execution"]
    provider = profile.model_metadata.get("provider")
    model = profile.model_metadata.get("model")
    if provider or model:
        lines.append(f"- Provider: `{provider or 'unknown'}`")
        lines.append(f"- Model: `{model or 'unknown'}`")
    if profile.tool_trace_refs:
        lines.append("- Tool trace refs:")
        lines.extend(f"  - `{ref}`" for ref in profile.tool_trace_refs[:40])
    if profile.validation_findings:
        lines.append("- Validation findings:")
        lines.extend(
            f"  - {finding.severity} `{finding.check}`: {finding.message}"
            for finding in profile.validation_findings[:40]
        )
    if len(lines) == 1:
        lines.append("- None recorded.")
    return "\n".join(lines)
