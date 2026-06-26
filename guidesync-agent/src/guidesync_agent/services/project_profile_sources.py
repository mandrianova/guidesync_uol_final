from __future__ import annotations

import re
from pathlib import Path

from guidesync_agent.schemas import (
    ProjectConfig,
    ProjectProfileEvidenceRef,
    ProjectProfileRepositoryMapItem,
    ProjectProfileSourceRef,
)

PROFILE_TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".json",
    ".md",
    ".mdx",
    ".py",
    ".rst",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
PROFILE_SKIP_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "outputs",
    "var",
}
MAX_PROFILE_FILES = 200
MAX_PROFILE_TEXT_FILES = 80
MAX_PROFILE_FILE_BYTES = 120_000


def normalized_profile_path(path: str | None) -> str:
    if path is None:
        return "docs/"
    value = path.strip().lstrip("/")
    return value or "."


class ProfileDocuments:
    def __init__(
        self,
        *,
        files: list[str],
        text_files: list[str],
        headings: list[str],
        evidence_refs: list[ProjectProfileEvidenceRef],
        warnings: list[str],
    ) -> None:
        self.files = files
        self.text_files = text_files
        self.headings = headings
        self.evidence_refs = evidence_refs
        self.warnings = warnings


def load_profile_documents(
    project: ProjectConfig,
    repository_data: list[
        tuple[ProjectProfileRepositoryMapItem, ProjectProfileSourceRef, list[str]]
    ],
) -> ProfileDocuments:
    files: list[str] = []
    text_files: list[str] = []
    headings: list[str] = []
    warnings: list[str] = []
    evidence_refs: list[ProjectProfileEvidenceRef] = []
    readable_sources = [source for _, source, _ in repository_data if source.local_path is not None]
    if not readable_sources:
        return ProfileDocuments(
            files=[],
            text_files=[],
            headings=[],
            evidence_refs=[],
            warnings=["no locally available repositories for profile analysis"],
        )

    for source in readable_sources:
        repo_root = Path(str(source.local_path)).resolve()
        if not repo_root.exists():
            warnings.append(f"profile repository path does not exist: {repo_root}")
            continue
        for path in sorted(repo_root.rglob("*")):
            if len(files) >= MAX_PROFILE_FILES:
                warnings.append(f"profile file scan stopped after {MAX_PROFILE_FILES} files")
                break
            if not path.is_file():
                continue
            try:
                relative = path.relative_to(repo_root)
            except ValueError:
                continue
            if any(part in PROFILE_SKIP_PARTS for part in relative.parts):
                continue
            relative_path = relative.as_posix()
            files.append(relative_path)
            evidence_refs.append(
                ProjectProfileEvidenceRef(
                    path=relative_path,
                    repository_id=source.repository_id,
                    reason="profile file path evidence",
                )
            )
            if (
                len(text_files) >= MAX_PROFILE_TEXT_FILES
                or path.suffix.lower() not in PROFILE_TEXT_SUFFIXES
            ):
                continue
            try:
                if path.stat().st_size > MAX_PROFILE_FILE_BYTES:
                    warnings.append(f"profile skipped large file: {relative_path}")
                    continue
                content = path.read_text(encoding="utf-8")
            except OSError as exc:
                warnings.append(f"profile could not read {relative_path}: {exc}")
                continue
            except UnicodeDecodeError:
                warnings.append(f"profile skipped non-text file: {relative_path}")
                continue
            text_files.append(relative_path)
            headings.extend(markdown_headings(content))
            evidence_refs.append(
                ProjectProfileEvidenceRef(
                    path=relative_path,
                    repository_id=source.repository_id,
                    reason="profile text evidence",
                )
            )
        if len(files) >= MAX_PROFILE_FILES:
            break
    if not files:
        warnings.append("no project files found for profile analysis")
    return ProfileDocuments(
        files=files,
        text_files=text_files,
        headings=headings,
        evidence_refs=evidence_refs,
        warnings=warnings,
    )


def markdown_headings(text: str) -> list[str]:
    headings: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if match:
            headings.append(match.group(1).strip(" #"))
    return headings
