from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
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
from guidesync_agent.services.text_normalization import tokenize_text
from guidesync_agent.tools import repository as repository_tools

DIFF_WINDOW_LIMIT = 8_000
FILE_WINDOW_LIMIT = 4_000
MAX_SUMMARY_LINE_CHARS = 160
MAX_SUMMARY_LINES = 3

DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
SOURCE_SUFFIXES = {
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".py",
    ".rb",
    ".rs",
    ".swift",
    ".ts",
    ".tsx",
}
CONFIG_SUFFIXES = {".json", ".toml", ".yaml", ".yml"}
TEST_PATH_PARTS = {"test", "tests", "__tests__", "spec", "specs"}
LOW_VALUE_TERMS = {
    "added",
    "changed",
    "diff",
    "file",
    "guide",
    "head",
    "index",
    "initial",
    "main",
    "markdown",
    "new",
    "old",
    "repo",
    "src",
    "status",
    "test",
    "update",
    "workflow",
}


class ChangedFileCategory(StrEnum):
    ASSET = "asset"
    CONFIG = "config"
    DOCS = "docs"
    SOURCE = "source"
    TESTS = "tests"
    UI = "ui"


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
) -> list[FileChangeSummary]:
    requests = [change_analysis_request(context, changed_file) for changed_file in changed_files]
    results = analyze_code_change_group_with_subagent(
        CodeChangeAnalysisGroupRequest(work_unit_id=work_unit_id, changes=requests),
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


def classify_changed_file(path: str) -> ChangedFileCategory:
    path_obj = Path(path)
    suffix = path_obj.suffix.lower()
    parts = {part.lower() for part in path_obj.parts}
    category = ChangedFileCategory.ASSET
    if suffix in DOC_SUFFIXES or "docs" in parts or path_obj.name.lower() == "readme.md":
        category = ChangedFileCategory.DOCS
    elif parts & TEST_PATH_PARTS or ".test." in path or ".spec." in path:
        category = ChangedFileCategory.TESTS
    elif suffix in {".tsx", ".jsx", ".css", ".html"}:
        category = ChangedFileCategory.UI
    elif suffix in SOURCE_SUFFIXES:
        category = ChangedFileCategory.SOURCE
    elif suffix in CONFIG_SUFFIXES:
        category = ChangedFileCategory.CONFIG
    return category


def summarize_diff_stats(diff: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def summarize_changed_lines(diff: str) -> list[str]:
    previews: list[str] = []
    for line in diff.splitlines():
        if line.startswith(("+++", "---", "@@", "diff --git", "index ")):
            continue
        if not line.startswith(("+", "-")):
            continue
        preview = line[1:].strip()
        if not preview:
            continue
        previews.append(preview[:MAX_SUMMARY_LINE_CHARS])
        if len(previews) >= MAX_SUMMARY_LINES:
            break
    return previews


def extract_keywords(text: str, path: str) -> list[str]:
    tokens = [token for token in tokenize_text(text) if token not in LOW_VALUE_TERMS]
    counts = Counter(tokens)
    for part in Path(path).parts:
        for token in tokenize_text(part):
            if token not in LOW_VALUE_TERMS:
                counts[token] += 2
    return [token for token, _ in counts.most_common(12)]


def docs_search_terms(
    keywords: list[str],
    path: str,
    category: ChangedFileCategory,
) -> list[str]:
    path_terms = [token for token in tokenize_text(Path(path).stem) if token not in LOW_VALUE_TERMS]
    candidates = [*path_terms, *keywords]
    if category is not ChangedFileCategory.DOCS:
        candidates.append(category.value)
    seen: set[str] = set()
    terms: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        terms.append(candidate)
        if len(terms) >= 8:
            break
    return terms


def build_technical_summary(
    path: str,
    status: str,
    diff_stats: tuple[int, int],
    changed_line_preview: list[str],
) -> str:
    additions, deletions = diff_stats
    action = status_label(status)
    summary = f"{action} `{path}` with {additions} additions and {deletions} deletions."
    if changed_line_preview:
        summary += " Key changed text mentions: " + "; ".join(changed_line_preview) + "."
    return summary


def status_label(status: str) -> str:
    first = status[:1]
    labels = {
        "A": "Added",
        "C": "Copied",
        "D": "Deleted",
        "M": "Modified",
        "R": "Renamed",
        "T": "Changed type for",
        "U": "Updated unresolved merge state for",
    }
    return labels.get(first, f"Changed ({status})")


def product_impact_for(path: str, category: ChangedFileCategory, audience: str) -> str:
    impact = (
        f"Non-text or ancillary file `{path}` changed; review whether it affects documentation."
    )
    if category is ChangedFileCategory.DOCS:
        impact = (
            f"Documentation content changed for {audience}; verify related guides and release "
            "notes stay aligned with the new wording."
        )
    elif category is ChangedFileCategory.TESTS:
        impact = (
            "Test coverage changed; documentation may need to mention the behavior protected by "
            "the updated tests."
        )
    elif category is ChangedFileCategory.UI:
        impact = (
            "User-facing UI code changed; documentation should check screenshots, workflow steps, "
            "and labels that reference this screen."
        )
    elif category is ChangedFileCategory.CONFIG:
        impact = (
            "Configuration changed; setup, deployment, and troubleshooting documentation may need "
            "updates."
        )
    elif category is ChangedFileCategory.SOURCE:
        impact = (
            "Implementation code changed; the main agent should review whether developer or user "
            "documentation describes the affected behavior."
        )
    return impact


def project_profile_context(project_profile: ProjectProfileSnapshot | None) -> str:
    if project_profile is None:
        return ""
    if project_profile.agent_context.strip():
        return project_profile.agent_context
    return "\n".join(
        [
            project_profile.summary,
            project_profile.project_description,
            " ".join(project_profile.project_structure),
            " ".join(project_profile.architecture),
            " ".join(project_profile.core_concepts),
            " ".join(project_profile.taxonomy.categories),
        ]
    )


def tool_error_note(prefix: str, error: object | None) -> str:
    if error is None:
        return prefix
    code = getattr(error, "code", "unknown")
    message = getattr(error, "message", str(error))
    return f"{prefix}: {code}: {message}"
