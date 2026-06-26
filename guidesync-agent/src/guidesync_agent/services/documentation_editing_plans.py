from __future__ import annotations

import json
from pathlib import Path

from guidesync_agent.schemas import (
    DocumentationEditOperation,
    DocumentationEditPlan,
    DocumentationEditPlanItem,
    DocumentationEditSection,
    DocumentationUpdate,
    FileChangeSummary,
)
from guidesync_agent.services.documentation_editing_sections import (
    first_markdown_heading,
    markdown_section_exists,
)

GENERATED_UPDATE_HEADING = "GuideSync Documentation Update"


def edit_section_from_update(update: DocumentationUpdate) -> DocumentationEditSection:
    markdown = update.proposed_update_markdown.strip()
    heading = first_markdown_heading(markdown) or update.title.strip() or GENERATED_UPDATE_HEADING
    if first_markdown_heading(markdown) is None:
        markdown = f"## {heading}\n\n{markdown}"
    return DocumentationEditSection(heading=heading, markdown=markdown.rstrip() + "\n")


def build_edit_plan(
    target_file: Path,
    target_path: str,
    docs_path: str,
    update: DocumentationUpdate,
    file_summaries: list[FileChangeSummary],
    *,
    existed: bool,
    section_heading: str,
) -> DocumentationEditPlan:
    if not existed:
        operation = DocumentationEditOperation.CREATE_DOC
        reason = "No existing documentation target matched the changed files."
    elif markdown_section_exists(target_file.read_text(encoding="utf-8"), section_heading):
        operation = DocumentationEditOperation.UPDATE_SECTION
        reason = "Existing section heading matched the generated update."
    else:
        operation = DocumentationEditOperation.ADD_SECTION
        reason = "Selected an existing documentation page and added a new focused section."

    warnings = []
    if not file_summaries:
        warnings.append("No changed-file summaries were available for target selection.")

    return DocumentationEditPlan(
        target_path=target_path,
        docs_path=docs_path,
        items=[
            DocumentationEditPlanItem(
                path=target_path,
                operation=operation,
                heading=section_heading,
                reason=reason,
                evidence_refs=[reference.source for reference in update.evidence_used],
                expected_audience_impact=update.user_facing_change,
            )
        ],
        warnings=warnings,
    )


def write_json_artifact(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
