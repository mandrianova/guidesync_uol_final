from __future__ import annotations

import re
import subprocess
from pathlib import Path

from guidesync_agent.schemas import (
    CommitEvidence,
    DiffHint,
    DocumentationEvidence,
    EvidenceBundle,
    FileChange,
    RepositoryInput,
)

USER_FACING_FILE_HINTS = (
    "routes/",
    "pages/",
    "app/",
    "components/",
    "features/",
    "templates/",
    "docs/",
)

USER_FACING_TEXT_HINTS = (
    "add",
    "button",
    "domain",
    "form",
    "guide",
    "label",
    "page",
    "settings",
    "user",
    "workflow",
)


def run_git(repo: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def collect_repository_evidence(
    repository: RepositoryInput,
) -> tuple[list[CommitEvidence], list[str]]:
    repo = repository.path.expanduser().resolve()
    warnings: list[str] = []
    if not (repo / ".git").exists():
        return [], [f"{repository.name}: not a git repository: {repo}"]

    log_args = [
        "log",
        repository.ref,
        f"--since={repository.since}",
        "--date=short",
        "--pretty=format:%H%x1f%ad%x1f%s%x1f%b%x1e",
    ]
    if repository.until:
        log_args.insert(3, f"--until={repository.until}")
    if repository.paths:
        log_args.extend(["--", *repository.paths])

    try:
        raw_log = run_git(repo, log_args)
    except subprocess.CalledProcessError as exc:
        return [], [f"{repository.name}: git log failed: {exc.stderr.strip()}"]

    commits: list[CommitEvidence] = []
    for record in raw_log.split("\x1e"):
        if not record.strip():
            continue
        parts = record.split("\x1f", maxsplit=3)
        if len(parts) < 3:
            continue
        if len(parts) == 3:
            parts.append("")
        sha, date, subject, body = [part.strip() for part in parts]
        files = collect_commit_files(repo, sha, repository.paths)
        file_stats = collect_file_stats(repo, sha, repository.paths)
        diff_hints = collect_diff_hints(repo, sha, repository.paths)
        commits.append(
            CommitEvidence(
                repo=repository.name,
                sha=sha,
                short_sha=sha[:8],
                date=date,
                subject=subject,
                body=body,
                files=files,
                file_stats=file_stats,
                diff_hints=diff_hints,
                user_facing_score=score_commit(subject, body, files, diff_hints),
            )
        )
        if len(commits) >= repository.max_commits:
            break
    return commits, warnings


def collect_commit_files(repo: Path, sha: str, paths: list[str]) -> list[str]:
    args = ["show", "--name-only", "--pretty=format:", sha]
    if paths:
        args.extend(["--", *paths])
    raw = run_git(repo, args)
    return [line.strip() for line in raw.splitlines() if line.strip()]


def collect_file_stats(repo: Path, sha: str, paths: list[str]) -> list[FileChange]:
    args = ["show", "--numstat", "--pretty=format:", sha]
    if paths:
        args.extend(["--", *paths])
    raw = run_git(repo, args)
    stats: list[FileChange] = []
    for line in raw.splitlines():
        added, removed, file_path, *_ = [*line.split("\t"), "", ""]
        if not file_path:
            continue
        stats.append(
            FileChange(
                file=file_path,
                added=None if added == "-" else int(added),
                removed=None if removed == "-" else int(removed),
            )
        )
    return stats


def collect_diff_hints(repo: Path, sha: str, paths: list[str]) -> list[DiffHint]:
    args = ["show", "--format=", "--unified=0", "--no-ext-diff", sha]
    if paths:
        args.extend(["--", *paths])
    raw = run_git(repo, args)
    hints: list[DiffHint] = []
    current_file = ""
    seen: set[tuple[str, str]] = set()
    for line in raw.splitlines():
        if line.startswith("diff --git "):
            match = re.search(r" b/(.+)$", line)
            current_file = match.group(1) if match else ""
            continue
        if not current_file or not line.startswith("+") or line.startswith("+++"):
            continue
        hint = meaningful_line(line[1:])
        if not hint:
            continue
        key = (current_file, hint)
        if key in seen:
            continue
        seen.add(key)
        hints.append(DiffHint(file=current_file, hint=hint))
        if len(hints) >= 20:
            break
    return hints


def meaningful_line(line: str) -> str | None:
    stripped = re.sub(r"\s+", " ", line.strip())
    if len(stripped) < 6:
        return None
    if stripped.startswith(("import ", "export ", "from ", "//", "/*", "*")):
        return None
    label_match = re.search(
        r"(?:title|label|placeholder|description|helperText|aria-label|name|text)\s*[:=]\s*[\"'`]([^\"'`]{4,140})",
        stripped,
    )
    if label_match:
        return label_match.group(1).strip()
    if re.search(r"[A-Za-z][A-Za-z ]{8,}", stripped):
        return stripped[:180]
    return None


def score_commit(subject: str, body: str, files: list[str], hints: list[DiffHint]) -> int:
    text = f"{subject}\n{body}\n{' '.join(h.hint for h in hints)}".lower()
    score = sum(2 for hint in USER_FACING_TEXT_HINTS if hint in text)
    for file_path in files:
        lowered = file_path.lower()
        if any(hint in lowered for hint in USER_FACING_FILE_HINTS):
            score += 2
        if lowered.endswith((".tsx", ".jsx", ".vue", ".svelte", ".html", ".md", ".mdx")):
            score += 1
    return score


def collect_documentation(
    paths: list[tuple[str, Path, str | None]],
) -> tuple[list[DocumentationEvidence], list[str]]:
    docs: list[DocumentationEvidence] = []
    warnings: list[str] = []
    for name, path, description in paths:
        resolved = path.expanduser().resolve()
        if not resolved.exists():
            warnings.append(f"{name}: documentation path does not exist: {resolved}")
            continue
        if resolved.is_dir():
            candidates = sorted(
                item for item in resolved.rglob("*") if item.suffix.lower() in {".md", ".txt"}
            )[:20]
        else:
            candidates = [resolved]
        for candidate in candidates:
            text = candidate.read_text(encoding="utf-8", errors="replace")
            docs.append(
                DocumentationEvidence(
                    name=name,
                    path=str(candidate),
                    excerpt=f"{description or ''}\n{text[:4000]}".strip(),
                )
            )
    return docs, warnings


def collect_evidence(repositories: list[RepositoryInput], documentation: list) -> EvidenceBundle:
    bundle = EvidenceBundle()
    for repository in repositories:
        bundle.repositories.append(str(repository.path))
        commits, warnings = collect_repository_evidence(repository)
        bundle.commits.extend(commits)
        bundle.warnings.extend(warnings)
    docs, doc_warnings = collect_documentation(
        [(doc.name, doc.path, doc.description) for doc in documentation]
    )
    bundle.documentation.extend(docs)
    bundle.warnings.extend(doc_warnings)
    bundle.commits.sort(key=lambda commit: (commit.user_facing_score, commit.date), reverse=True)
    return bundle
