from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from guidesync_agent.schemas import (
    DocumentationUpdate,
    EvidenceReference,
    FileChangeSummary,
    GuideSyncRunRequest,
    KnowledgeSearchResult,
    ProjectProfileSnapshot,
    ValidationFinding,
)
from guidesync_agent.services.change_analysis import summarize_changed_files
from guidesync_agent.storage import (
    create_project_profile_store,
    project_id_from_run_id,
)
from guidesync_agent.tools.knowledge import search_knowledge_base
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
) -> DocumentationUpdateWorkflowContext:
    context = DocumentationUpdateWorkflowContext()
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
        if result.ok:
            changed_files.extend(
                {
                    "repository_id": repository.repository_id,
                    **item.model_dump(mode="json"),
                }
                for item in result.files
            )
            context.file_summaries.extend(
                summarize_changed_files(
                    repository.project_id,
                    repository.repository_id,
                    result.files,
                    goal=request.goal,
                    audience=request.audience.value,
                    project_profile=context.project_profile,
                    base_ref=result.base_ref,
                    head_ref=result.head_ref,
                )
            )
        elif result.error:
            context.findings.append(
                ValidationFinding(
                    severity="warning",
                    check="changed-file-manifest",
                    message=result.error.message,
                )
            )
    context.artifacts["changed-files.json"] = write_workflow_artifact(
        output_dir / "changed-files.json",
        {"files": changed_files},
    )
    context.file_summaries = write_file_summary_artifacts(output_dir, context.file_summaries)
    context.artifacts["file-summaries.json"] = write_workflow_artifact(
        output_dir / "file-summaries.json",
        {
            "summaries": [
                summary.model_dump(mode="json") for summary in context.file_summaries
            ]
        },
    )

    if project_id:
        if context.project_profile:
            context.artifacts["project-profile.json"] = write_workflow_artifact(
                output_dir / "project-profile.json",
                context.project_profile.model_dump(mode="json"),
            )
        retrieval_query = retrieval_query_for(request.goal, context.file_summaries)
        context.retrieved_docs = search_knowledge_base(
            project_id,
            retrieval_query,
            audience=request.audience.value,
            limit=8,
        )
        context.artifacts["retrieved-docs.json"] = write_workflow_artifact(
            output_dir / "retrieved-docs.json",
            {
                "results": [
                    result.model_dump(mode="json") for result in context.retrieved_docs
                ]
            },
        )
    return context


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


def project_id_for_request(request: GuideSyncRunRequest) -> str | None:
    return (
        next(
            (repository.project_id for repository in request.repositories if repository.project_id),
            None,
        )
        or project_id_from_run_id(request.run_id)
    )


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
