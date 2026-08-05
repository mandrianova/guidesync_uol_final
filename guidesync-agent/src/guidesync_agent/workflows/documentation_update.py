from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from guidesync_agent.schemas import (
    DocumentationEditResult,
    DocumentationUpdate,
    EvidenceReference,
    FileChangeSummary,
    GuideSyncRunRequest,
    KnowledgeConceptKind,
    KnowledgeSearchResult,
    ProjectProfileSnapshot,
    ValidationFinding,
)
from guidesync_agent.services.change_analysis import (
    ChangeAnalysisContext,
    summarize_changed_files,
)
from guidesync_agent.services.documentation_editing import apply_documentation_edit
from guidesync_agent.services.validation import ValidationService
from guidesync_agent.storage import (
    create_project_profile_store,
    project_id_from_run_id,
)
from guidesync_agent.tools.knowledge import KnowledgeBaseSearchRequest, search_knowledge_base
from guidesync_agent.tools.repository import list_changed_files


@dataclass
class DocumentationUpdateWorkflowContext:
    artifacts: dict[str, str] = field(default_factory=dict)
    findings: list[ValidationFinding] = field(default_factory=list)
    retrieved_docs: list[KnowledgeSearchResult] = field(default_factory=list)
    file_summaries: list[FileChangeSummary] = field(default_factory=list)
    project_profile: ProjectProfileSnapshot | None = None


def prepare_documentation_update_workflow(
    request: GuideSyncRunRequest,
    *,
    workflow_task_id: str | None = None,
) -> DocumentationUpdateWorkflowContext:
    context = DocumentationUpdateWorkflowContext()
    validation_service = ValidationService()
    output_dir = request.report.output_dir / "workflow"
    output_dir.mkdir(parents=True, exist_ok=True)
    project_id = project_id_for_request(request)

    if project_id:
        context.project_profile = project_profile_for_request(request, project_id)

    changed_files: list[dict[str, object]] = []
    for repository in request.repositories:
        if not repository.project_id or not repository.repository_id:
            continue
        result = list_changed_files(repository.project_id, repository.repository_id)
        context.findings.extend(validation_service.after_tool_result("list_changed_files", result))
        if result.error is None:
            changed_files.extend(
                {
                    "repository_id": repository.repository_id,
                    **item.model_dump(mode="json"),
                }
                for item in result.files
            )
            context.file_summaries.extend(
                summarize_changed_files(
                    ChangeAnalysisContext(
                        project_id=repository.project_id,
                        repository_id=repository.repository_id,
                        run_id=request.run_id,
                        workflow_task_id=workflow_task_id,
                        goal=request.goal,
                        audience=request.audience.value,
                        project_profile=context.project_profile,
                        base_ref=result.base_ref,
                        head_ref=result.head_ref,
                    ),
                    result.files,
                )
            )
    context.artifacts["changed-files.json"] = write_workflow_artifact(
        output_dir / "changed-files.json",
        {"files": changed_files},
    )
    context.file_summaries = write_file_summary_artifacts(output_dir, context.file_summaries)
    for summary in context.file_summaries:
        context.findings.extend(validation_service.after_file_summary(summary))
    context.artifacts["file-summaries.json"] = write_workflow_artifact(
        output_dir / "file-summaries.json",
        {"summaries": [summary.model_dump(mode="json") for summary in context.file_summaries]},
    )

    if project_id:
        if context.project_profile:
            context.artifacts["project-profile.json"] = write_workflow_artifact(
                output_dir / "project-profile.json",
                context.project_profile.model_dump(mode="json"),
            )
        retrieval_query = retrieval_query_for(request.goal, context.file_summaries)
        retrieval_terms = retrieval_terms_for(context.file_summaries)
        context.retrieved_docs = search_knowledge_base(
            KnowledgeBaseSearchRequest(
                project_id=project_id,
                query=retrieval_query,
                audience=request.audience.value,
                taxonomy_version=(
                    context.project_profile.taxonomy.version
                    if context.project_profile
                    else None
                ),
                tags=retrieval_terms["tags"],
                categories=retrieval_terms["categories"],
                keyphrases=retrieval_terms["keyphrases"],
                extracted_names=retrieval_terms["extracted_names"],
                concepts=retrieval_terms["concepts"],
                components=retrieval_terms["components"],
                workflows=retrieval_terms["workflows"],
                documentation_areas=retrieval_terms["documentation_areas"],
                limit=8,
            )
        )
        context.artifacts["retrieved-docs.json"] = write_workflow_artifact(
            output_dir / "retrieved-docs.json",
            {"results": [result.model_dump(mode="json") for result in context.retrieved_docs]},
        )
    return context


def apply_documentation_edit_to_update(
    request: GuideSyncRunRequest,
    update: DocumentationUpdate | None,
    context: DocumentationUpdateWorkflowContext,
) -> None:
    if update is None:
        return
    project_id = project_id_for_request(request)
    if project_id is None:
        return
    try:
        edit_result = apply_documentation_edit(
            project_id,
            update,
            context.file_summaries,
            output_dir=request.report.output_dir / "workflow" / "documentation-edit",
            run_id=request.run_id,
        )
    except Exception as exc:  # noqa: BLE001 - editing failure should not hide provider output
        context.findings.append(
            ValidationFinding(
                severity="warning",
                check="documentation-edit",
                message=f"Documentation edit failed: {exc}",
            )
        )
        return

    update.documentation_edit = edit_result
    context.artifacts["documentation-edit.json"] = write_workflow_artifact(
        request.report.output_dir / "workflow" / "documentation-edit.json",
        edit_result.model_dump(mode="json"),
    )
    if edit_result.patch_artifact_uri:
        context.artifacts["documentation.patch"] = edit_result.patch_artifact_uri
    if edit_result.edit_plan_artifact_uri:
        context.artifacts["documentation-edit-plan.json"] = edit_result.edit_plan_artifact_uri
    attach_documentation_edit_refs(update, edit_result)
    append_documentation_links(update, edit_result)
    context.findings.extend(ValidationService().after_documentation_edit(edit_result))


def attach_retrieved_docs_to_update(
    update: DocumentationUpdate | None,
    retrieved_docs: list[KnowledgeSearchResult],
) -> None:
    if update is None:
        return
    existing_sources = {reference.source for reference in update.evidence_used}
    for result in retrieved_docs[:5]:
        path = result.node.path or (result.chunk.path if result.chunk else None)
        heading = result.chunk.heading if result.chunk else result.node.name
        source = f"knowledge:{path}#{heading}"
        if source in existing_sources:
            continue
        update.evidence_used.append(
            EvidenceReference(
                source=source,
                detail=result.matched_text,
                relevance="Retrieved documentation reference used by the workflow.",
            )
        )
        existing_sources.add(source)


def attach_documentation_edit_refs(
    update: DocumentationUpdate,
    edit_result: DocumentationEditResult,
) -> None:
    existing_sources = {reference.source for reference in update.evidence_used}
    for path in edit_result.changed_docs:
        source = f"doc-change:{edit_result.repository_id}:{path}"
        if source in existing_sources:
            continue
        detail_parts = [f"updated `{path}`"]
        if edit_result.commit_sha:
            detail_parts.append("local documentation commit created")
        elif edit_result.patch_artifact_uri:
            detail_parts.append("patch artifact saved")
        update.evidence_used.append(
            EvidenceReference(
                source=source,
                detail=", ".join(detail_parts),
                relevance="Documentation file produced by the documentation editing workflow.",
            )
        )
        existing_sources.add(source)


def append_documentation_links(
    update: DocumentationUpdate,
    edit_result: DocumentationEditResult,
) -> None:
    if not edit_result.changed_docs:
        return
    if all(path in update.proposed_update_markdown for path in edit_result.changed_docs):
        return
    lines = ["", "## Documentation Changes", ""]
    lines.extend(f"- `{path}`" for path in edit_result.changed_docs)
    update.proposed_update_markdown = (
        update.proposed_update_markdown.rstrip() + "\n" + "\n".join(lines) + "\n"
    )


def project_id_for_request(request: GuideSyncRunRequest) -> str | None:
    return next(
        (repository.project_id for repository in request.repositories if repository.project_id),
        None,
    ) or project_id_from_run_id(request.run_id)


def project_profile_for_request(
    request: GuideSyncRunRequest,
    project_id: str,
) -> ProjectProfileSnapshot | None:
    store = create_project_profile_store()
    if request.project_profile_snapshot_id:
        profile = store.get(request.project_profile_snapshot_id)
        if profile is not None:
            return profile
    return store.latest(project_id)


def retrieval_query_for(goal: str, file_summaries: list[FileChangeSummary]) -> str:
    terms: list[str] = []
    for summary in file_summaries:
        terms.extend(summary.docs_to_search)
    selected_terms = dedupe_preserve_order(terms)[:20]
    return " ".join([goal, *selected_terms])


def retrieval_terms_for(file_summaries: list[FileChangeSummary]) -> dict[str, list[str]]:
    terms = {
        "tags": [],
        "categories": [],
        "keyphrases": [],
        "extracted_names": [],
        "concepts": [],
        "components": [],
        "workflows": [],
        "documentation_areas": [],
    }
    for summary in file_summaries:
        terms["tags"].extend(summary.documentation_keywords)
        terms["keyphrases"].extend(summary.documentation_search_intents)
        terms["extracted_names"].extend(summary.affected_components)
        terms["components"].extend(summary.affected_components)
        terms["workflows"].extend(summary.affected_workflows)
        for match in summary.taxonomy_matches:
            if match.kind == KnowledgeConceptKind.CATEGORY:
                terms["categories"].append(match.value)
            elif match.kind == KnowledgeConceptKind.COMPONENT:
                terms["components"].append(match.value)
            elif match.kind == KnowledgeConceptKind.WORKFLOW:
                terms["workflows"].append(match.value)
            elif match.kind == KnowledgeConceptKind.DOCUMENTATION_AREA:
                terms["documentation_areas"].append(match.value)
            else:
                terms["concepts"].append(match.value)
    return {key: dedupe_preserve_order(values)[:20] for key, values in terms.items()}


def write_file_summary_artifacts(
    output_dir: Path,
    file_summaries: list[FileChangeSummary],
) -> list[FileChangeSummary]:
    summary_dir = output_dir / "file-summaries"
    written: list[FileChangeSummary] = []
    for index, summary in enumerate(file_summaries, start=1):
        artifact_path = summary_dir / f"{index:03d}-{safe_artifact_name(summary.path)}.json"
        updated = summary.model_copy(update={"artifact_uri": str(artifact_path)})
        write_workflow_artifact(artifact_path, updated.model_dump(mode="json"))
        written.append(updated)
    return written


def safe_artifact_name(path: str) -> str:
    safe = "".join(character if character.isalnum() else "-" for character in path.lower())
    safe = "-".join(part for part in safe.split("-") if part)
    return safe[:120] or "changed-file"


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def write_workflow_artifact(path: Path, payload: dict[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return str(path)
