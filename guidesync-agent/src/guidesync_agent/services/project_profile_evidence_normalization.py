from __future__ import annotations

import re

from guidesync_agent.schemas import (
    ProjectProfileAgentEvidence,
    ProjectProfileAgentOutput,
)


def canonicalize_project_profile_output(
    output: ProjectProfileAgentOutput,
    evidence: ProjectProfileAgentEvidence,
) -> ProjectProfileAgentOutput:
    _ = evidence
    return output.model_copy(
        update={
            "summary": compact_text(output.summary),
            "project_description": compact_text(output.project_description),
            "project_structure": compact_markdown(output.project_structure),
            "architecture": compact_markdown(output.architecture),
            "core_concepts": unique_values(output.core_concepts),
            "categories": unique_values(output.categories),
        }
    )


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def compact_markdown(value: str) -> str:
    lines = [line.rstrip() for line in value.strip().splitlines()]
    return "\n".join(line for line in lines if line.strip())


def unique_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(compact_text(value) for value in values if value.strip()))
