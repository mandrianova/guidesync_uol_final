from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, Field

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
PROFILE_SECRET_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_dsa",
    "known_hosts",
}
PROFILE_SECRET_RE = re.compile(
    r"(^|[./_-])(secret|credentials?|private[-_]?key|api[-_]?key|token|password)([./_-]|$)",
    re.IGNORECASE,
)
MAX_PROFILE_FILES = 200
MAX_PROFILE_TEXT_FILES = 80
MAX_PROFILE_FILE_BYTES = 120_000
MAX_PROFILE_SAMPLE_CHARS = 4_000
MAX_PROFILE_TERMS = 16


def normalized_profile_path(path: str | None) -> str:
    if path is None:
        return "docs/"
    value = path.strip().lstrip("/")
    return value or "."


class ProfileTextSample(BaseModel):
    path: str
    repository_id: str | None = None
    headings: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
    excerpt: str = ""
    truncated: bool = False


class ProfileDocuments(BaseModel):
    files: list[str] = Field(default_factory=list)
    text_files: list[str] = Field(default_factory=list)
    headings: list[str] = Field(default_factory=list)
    text_samples: list[ProfileTextSample] = Field(default_factory=list)
    evidence_refs: list[ProjectProfileEvidenceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def load_profile_documents(
    project: ProjectConfig,
    repository_data: list[
        tuple[ProjectProfileRepositoryMapItem, ProjectProfileSourceRef, list[str]]
    ],
) -> ProfileDocuments:
    files: list[str] = []
    text_files: list[str] = []
    headings: list[str] = []
    text_samples: list[ProfileTextSample] = []
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
            if is_likely_secret_path(relative):
                warnings.append(f"profile skipped likely secret file: {relative_path}")
                continue
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
            sample = profile_text_sample(source, relative_path, content)
            text_samples.append(sample)
            headings.extend(sample.headings)
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
        text_samples=text_samples,
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


def profile_text_sample(
    source: ProjectProfileSourceRef,
    relative_path: str,
    content: str,
) -> ProfileTextSample:
    truncated = len(content) > MAX_PROFILE_SAMPLE_CHARS
    excerpt = content[:MAX_PROFILE_SAMPLE_CHARS]
    return ProfileTextSample(
        path=relative_path,
        repository_id=source.repository_id,
        headings=markdown_headings(excerpt),
        symbols=extract_symbol_names(excerpt),
        key_terms=extract_source_terms(excerpt),
        excerpt=excerpt,
        truncated=truncated,
    )


def extract_symbol_names(text: str) -> list[str]:
    candidates = re.findall(r"\b[A-Z][A-Za-z0-9]+(?:[A-Z][a-z0-9]+)[A-Za-z0-9]*\b", text)
    candidates.extend(
        re.findall(r"\b(?:class|function|def|const)\s+([A-Za-z_][A-Za-z0-9_]*)", text)
    )
    return unique_values(candidates)[:MAX_PROFILE_TERMS]


def extract_source_terms(text: str) -> list[str]:
    terms = re.findall(r"\b[a-z][a-z0-9]+(?:[-_ ][a-z0-9]+){0,3}\b", text.lower())
    return unique_values(term.replace("_", "-").strip() for term in terms)[:MAX_PROFILE_TERMS]


def is_likely_secret_path(path: Path) -> bool:
    name = path.name.lower()
    return name in PROFILE_SECRET_NAMES or bool(PROFILE_SECRET_RE.search(path.as_posix()))


def unique_values(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result
