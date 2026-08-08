from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from guidesync_agent.agent_runtime.code_change import (
    CodeChangeAnalysisEvidence,
    CodeChangeAnalysisGroupRequest,
    CodeChangeAnalysisProvider,
    CodeChangeAnalysisRequest,
    CodeChangeGroupAnalysisProvider,
    analyze_code_change_group_with_subagent,
)
from guidesync_agent.schemas import (
    ChangedFileRef,
    CodeChangeEvidenceRef,
    FileChangeSummary,
    ProjectProfileSnapshot,
    RepositoryDiffWindow,
    RepositoryFileWindow,
)
from guidesync_agent.services.change_evidence_packet import (
    CHANGE_EVIDENCE_BUDGET,
    ChangeEvidenceBuildContext,
    build_change_evidence,
)
from guidesync_agent.services.change_summary import (
    ChangedFileCategory,
    build_technical_summary,
    classify_changed_file,
    docs_search_terms,
    extract_keywords,
    product_impact_for,
    project_profile_context,
    summarize_changed_lines,
    summarize_diff_stats,
    tool_error_note,
)
from guidesync_agent.tools import repository as repository_tools

DIFF_WINDOW_LIMIT = CHANGE_EVIDENCE_BUDGET.max_diff_chars_per_file
FILE_WINDOW_LIMIT = CHANGE_EVIDENCE_BUDGET.max_current_file_chars


@dataclass(frozen=True)
class ChangeAnalysisContext:
    project_id: str
    repository_id: str
    goal: str
    audience: str
    run_id: str | None = None
    workflow_task_id: str | None = None
    project_profile: ProjectProfileSnapshot | None = None
    analysis_provider: CodeChangeAnalysisProvider | CodeChangeGroupAnalysisProvider | None = None
    base_ref: str | None = None
    head_ref: str = "HEAD"


@dataclass(frozen=True)
class ChangeInspection:
    path: str
    category: ChangedFileCategory
    diff_window: RepositoryDiffWindow
    file_window: RepositoryFileWindow | None
    risk_notes: list[str]
    needs_review: bool


def summarize_changed_file(
    context: ChangeAnalysisContext,
    changed_file: ChangedFileRef,
) -> FileChangeSummary:
    return summarize_change_group(context, [changed_file], work_unit_id=changed_file.path)[0]


def summarize_change_group(
    context: ChangeAnalysisContext,
    changed_files: list[ChangedFileRef],
    *,
    work_unit_id: str,
    grouping_reason: str = "",
    connectivity_evidence: list[str] | None = None,
) -> list[FileChangeSummary]:
    requests = [change_analysis_request(context, changed_file) for changed_file in changed_files]
    prepared_evidence = build_change_evidence(
        ChangeEvidenceBuildContext(
            project_id=context.project_id,
            repository_id=context.repository_id,
            goal=context.goal,
            audience=context.audience,
        ),
        requests,
    )
    results = analyze_code_change_group_with_subagent(
        CodeChangeAnalysisGroupRequest(
            work_unit_id=work_unit_id,
            grouping_reason=grouping_reason,
            connectivity_evidence=connectivity_evidence or [],
            changes=requests,
            changed_symbols=prepared_evidence.changed_symbols,
            related_references=prepared_evidence.related_references,
            knowledge_hits=prepared_evidence.knowledge_hits,
            evidence_budget=prepared_evidence.budget,
        ),
        provider=context.analysis_provider,
    )
    return [
        result.summary.model_copy(update={"analysis_artifact": result.artifact})
        for result in results
    ]


def change_analysis_request(
    context: ChangeAnalysisContext,
    changed_file: ChangedFileRef,
) -> CodeChangeAnalysisRequest:
    inspection = inspect_changed_file(context, changed_file)
    fallback_summary = build_fallback_summary(context, changed_file, inspection)
    diff_available = inspection.diff_window.error is None
    file_window = inspection.file_window
    evidence_refs = code_change_evidence_refs(
        context.repository_id,
        inspection.path,
        inspection.diff_window,
        file_window,
    )
    return CodeChangeAnalysisRequest(
        run_id=context.run_id,
        workflow_task_id=context.workflow_task_id,
        project_id=context.project_id,
        repository_id=context.repository_id,
        path=inspection.path,
        status=changed_file.status,
        goal=context.goal,
        audience=context.audience,
        fallback_summary=fallback_summary,
        evidence=CodeChangeAnalysisEvidence(
            diff=inspection.diff_window.diff if diff_available else "",
            current_file=(file_window.content if file_window and file_window.error is None else ""),
            diff_truncated=(
                inspection.diff_window.pagination.truncated if diff_available else False
            ),
            current_file_truncated=(
                file_window.pagination.truncated
                if file_window and file_window.error is None
                else False
            ),
            evidence_refs=evidence_refs,
        ),
        project_profile=context.project_profile,
    )


def inspect_changed_file(
    context: ChangeAnalysisContext,
    changed_file: ChangedFileRef,
) -> ChangeInspection:
    risk_notes: list[str] = []
    needs_review = False
    path = Path(changed_file.path).as_posix()
    category = classify_changed_file(path)

    diff_window = repository_tools.read_diff_window(
        context.project_id,
        context.repository_id,
        path=path,
        base_ref=context.base_ref,
        head_ref=context.head_ref,
        limit=DIFF_WINDOW_LIMIT,
    )
    diff_available = diff_window.error is None
    if not diff_available:
        needs_review = True
        risk_notes.append(tool_error_note("diff unavailable", diff_window.error))
    elif diff_window.pagination.truncated:
        needs_review = True
        risk_notes.append("diff window was truncated; summary only covers the first window")

    file_window = None
    if not changed_file.status.startswith("D"):
        file_window = repository_tools.read_file_window(
            context.project_id,
            context.repository_id,
            path,
            limit=FILE_WINDOW_LIMIT,
        )
        if file_window.error is not None:
            needs_review = True
            risk_notes.append(tool_error_note("file window unavailable", file_window.error))
        elif file_window.pagination.truncated:
            risk_notes.append("file window was truncated; keywords use the first window only")
    else:
        needs_review = True
        risk_notes.append("file was deleted; current content window was not read")

    if category in {
        ChangedFileCategory.SOURCE,
        ChangedFileCategory.UI,
        ChangedFileCategory.CONFIG,
    }:
        needs_review = True

    return ChangeInspection(
        path=path,
        category=category,
        diff_window=diff_window,
        file_window=file_window,
        risk_notes=risk_notes,
        needs_review=needs_review,
    )


def build_fallback_summary(
    context: ChangeAnalysisContext,
    changed_file: ChangedFileRef,
    inspection: ChangeInspection,
) -> FileChangeSummary:
    diff_window = inspection.diff_window
    file_window = inspection.file_window
    diff_available = diff_window.error is None
    path = inspection.path

    diff_stats = summarize_diff_stats(diff_window.diff if diff_available else "")
    changed_line_preview = summarize_changed_lines(diff_window.diff if diff_available else "")
    profile_text = project_profile_context(context.project_profile)
    keyword_source = "\n".join(
        item
        for item in [
            context.goal,
            context.audience,
            path,
            diff_window.diff if diff_available else "",
            file_window.content if file_window and file_window.error is None else "",
            profile_text,
        ]
        if item
    )
    keywords = extract_keywords(keyword_source, path)
    docs_to_search = docs_search_terms(keywords, path, inspection.category)
    technical_summary = build_technical_summary(
        path,
        changed_file.status,
        diff_stats,
        changed_line_preview,
    )
    return FileChangeSummary(
        repository_id=context.repository_id,
        path=path,
        status=changed_file.status,
        technical_summary=technical_summary,
        product_impact=product_impact_for(path, inspection.category, context.audience),
        documentation_keywords=keywords,
        docs_to_search=docs_to_search,
        risk_notes=inspection.risk_notes,
        needs_main_agent_review=inspection.needs_review,
    )


def code_change_evidence_refs(
    repository_id: str,
    path: str,
    diff_window: RepositoryDiffWindow,
    file_window: RepositoryFileWindow | None,
) -> list[CodeChangeEvidenceRef]:
    refs: list[CodeChangeEvidenceRef] = []
    diff_available = diff_window.error is None
    refs.append(
        CodeChangeEvidenceRef(
            source=f"{'diff' if diff_available else 'diff-error'}:{repository_id}:{path}",
            detail=window_evidence_detail(
                diff_window,
                success="Bounded raw diff window read by the code-change analyzer.",
                failure="Diff window could not be read by the code-change analyzer.",
            ),
        )
    )
    if file_window is not None:
        file_available = file_window.error is None
        refs.append(
            CodeChangeEvidenceRef(
                source=f"{'file' if file_available else 'file-error'}:{repository_id}:{path}",
                detail=window_evidence_detail(
                    file_window,
                    success="Bounded current-file window read by the code-change analyzer.",
                    failure="Current-file window could not be read by the code-change analyzer.",
                ),
            )
        )
    return refs


def window_evidence_detail(
    window: RepositoryDiffWindow | RepositoryFileWindow,
    *,
    success: str,
    failure: str,
) -> str:
    if window.error is None:
        return success
    return f"{failure} {window.error.code}: {window.error.message}"
