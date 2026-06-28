from __future__ import annotations

import json
import os
from pathlib import Path

from guidesync_agent.prompts.loader import load_prompt_file
from guidesync_agent.schemas import (
    ProjectConfig,
    ProjectProfileSnapshot,
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
        "## Project description",
        profile.project_description or "None recorded.",
        "",
        markdown_text("Project structure", profile.project_structure),
        markdown_text("Architecture", profile.architecture),
        markdown_list("Core concepts", profile.core_concepts),
        markdown_list("Documentation categories", profile.taxonomy.categories),
        "",
        markdown_list("Warnings", profile.warnings),
    ]
    return "\n".join(sections).rstrip() + "\n"


def markdown_list(title: str, items: list[str]) -> str:
    lines = [f"## {title}"]
    lines.extend(f"- {item}" for item in items)
    if len(lines) == 1:
        lines.append("- None recorded.")
    return "\n".join(lines)


def markdown_text(title: str, items: list[str]) -> str:
    lines = [f"## {title}"]
    text = "\n\n".join(item for item in items if item.strip())
    lines.append(text or "None recorded.")
    return "\n".join(lines)
