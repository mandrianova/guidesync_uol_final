from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from guidesync_agent.schemas import (
    DocumentationEditOperation,
    DocumentationEditPlan,
    DocumentationEditPlanItem,
    DocumentationEditSection,
    FileChangeSummary,
)
from guidesync_agent.services.documentation.sections import (
    markdown_section_exists,
)

GENERATED_UPDATE_HEADING = "GuideSync Documentation Update"
MAX_SECTION_HEADING_LENGTH = 72
LEADING_GOAL_VERBS = re.compile(r"^(?:add|describe|document|explain|update|write)\s+", re.I)


@dataclass(frozen=True)
class DocumentationEditPlanInput:
    project_id: str
    run_id: str
    target_file: Path
    target_path: str
    docs_path: str
    goal: str
    file_summaries: list[FileChangeSummary]
    existed: bool
    section_heading: str


def edit_section_from_markdown(markdown: str, heading: str) -> DocumentationEditSection:
    body = remove_first_heading(markdown.strip())
    body = normalize_section_headings(body)
    section_markdown = f"## {heading}\n"
    if body:
        section_markdown += f"\n{body.rstrip()}\n"
    return DocumentationEditSection(heading=heading, markdown=section_markdown)


def build_edit_plan(data: DocumentationEditPlanInput) -> DocumentationEditPlan:
    if not data.existed:
        operation = DocumentationEditOperation.CREATE_DOC
        reason = "No existing documentation target matched the changed files."
    elif markdown_section_exists(
        data.target_file.read_text(encoding="utf-8"),
        data.section_heading,
    ):
        operation = DocumentationEditOperation.UPDATE_SECTION
        reason = "Existing section heading matched the generated update."
    else:
        operation = DocumentationEditOperation.ADD_SECTION
        reason = "Selected an existing documentation page and added a new focused section."

    warnings = []
    if not data.file_summaries:
        warnings.append("No changed-file summaries were available for target selection.")

    identity = "\0".join(
        [
            data.project_id,
            data.run_id,
            data.target_path,
            operation.value,
            data.section_heading,
        ]
    )
    digest = hashlib.sha256(identity.encode()).hexdigest()[:16]
    plan_id = f"edit-plan-{digest}"

    return DocumentationEditPlan(
        id=plan_id,
        target_path=data.target_path,
        docs_path=data.docs_path,
        items=[
            DocumentationEditPlanItem(
                id=f"{plan_id}-item-1",
                path=data.target_path,
                operation=operation,
                heading=data.section_heading,
                reason=reason,
                evidence_refs=[
                    f"file-summary:{summary.repository_id}:{summary.path}"
                    for summary in data.file_summaries
                ],
                expected_audience_impact=data.goal,
            )
        ],
        warnings=warnings,
    )


def planned_section_heading(goal: str) -> str:
    first_clause = re.split(r"[,.;:!?]", goal, maxsplit=1)[0]
    heading = re.sub(r"\s+", " ", first_clause).strip()
    heading = LEADING_GOAL_VERBS.sub("", heading).strip()
    if len(heading) > MAX_SECTION_HEADING_LENGTH:
        heading = heading[: MAX_SECTION_HEADING_LENGTH + 1].rsplit(" ", maxsplit=1)[0]
    if heading:
        heading = heading[0].upper() + heading[1:]
    return heading or GENERATED_UPDATE_HEADING


def remove_first_heading(markdown: str) -> str:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if re.match(r"^#{1,6}\s+", line):
            del lines[index]
        break
    return "\n".join(lines).strip()


def normalize_section_headings(markdown: str) -> str:
    heading_levels = [
        len(match.group(1))
        for line in markdown.splitlines()
        if (match := re.match(r"^(#{1,6})\s+", line))
    ]
    if not heading_levels:
        return markdown
    offset = 3 - min(heading_levels)
    lines: list[str] = []
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,6})(\s+.*)$", line)
        if match is None:
            lines.append(line)
            continue
        level = min(6, max(3, len(match.group(1)) + offset))
        lines.append(f"{'#' * level}{match.group(2)}")
    return "\n".join(lines)


def write_json_artifact(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
