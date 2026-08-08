from __future__ import annotations

from collections import Counter
from enum import StrEnum
from pathlib import Path

from guidesync_agent.schemas import ProjectProfileSnapshot
from guidesync_agent.services.text_normalization import tokenize_text

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
