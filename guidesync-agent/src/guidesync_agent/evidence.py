from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from guidesync_agent.schemas import (
    CommitEvidence,
    DiffHint,
    DocumentationEvidence,
    EvidenceBundle,
    FileChange,
    RepositoryInput,
)
from guidesync_agent.services.repositories.cache import (
    RepositoryCacheService,
    git_ref_candidates,
    run_git,
)
from guidesync_agent.settings import get_settings

logger = logging.getLogger(__name__)
@dataclass(frozen=True)
class CommitCollectionContext:
    repo: Path
    repository: RepositoryInput
    warnings: list[str]


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

DATE_ONLY_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def collect_repository_evidence(
    repository: RepositoryInput,
) -> tuple[list[CommitEvidence], list[str]]:
    if repository.url:
        return collect_cached_repository_evidence(repository)
    return collect_local_repository_evidence(repository)


def collect_local_repository_evidence(
    repository: RepositoryInput,
) -> tuple[list[CommitEvidence], list[str]]:
    repository_path = repository.path or repository.local_path
    if repository_path is None:
        return [], [f"{repository.name}: repository path or URL is required"]
    repo = repository_path.expanduser().resolve()
    warnings: list[str] = []
    if not (repo / ".git").exists():
        return [], [f"{repository.name}: not a git repository: {repo}"]

    return collect_git_log_evidence(repo, repository, [repository.ref], warnings), warnings


def collect_git_log_evidence(
    repo: Path,
    repository: RepositoryInput,
    revisions: list[str],
    warnings: list[str],
) -> list[CommitEvidence]:
    log_args = ["log", *revisions]
    if repository.since:
        log_args.append(f"--since={git_date_boundary(repository.since, end_of_day=False)}")
    if repository.until:
        log_args.append(f"--until={git_date_boundary(repository.until, end_of_day=True)}")
    log_args.extend(
        [
            "--date=short",
            "--pretty=format:%H%x1f%ad%x1f%s%x1f%b%x1e",
        ]
    )
    if repository.paths:
        log_args.extend(["--", *repository.paths])

    try:
        raw_log = run_git(repo, log_args)
    except subprocess.CalledProcessError as exc:
        warnings.append(f"{repository.name}: git log failed: {exc.stderr.strip()}")
        return []

    return parse_commit_log(repo, repository, raw_log, warnings)


def git_date_boundary(value: str, *, end_of_day: bool) -> str:
    if not DATE_ONLY_PATTERN.fullmatch(value):
        return value
    time = "23:59:59" if end_of_day else "00:00:00"
    return f"{value}T{time}+00:00"


def chronological_commit_refs(
    repository: RepositoryInput,
    commits: list[CommitEvidence],
) -> tuple[str, str] | None:
    """Return selected history edges from the materialized Git repository."""
    repository_path = materialized_repository_path(repository)
    if repository_path is None or not commits:
        return None
    repo = repository_path.expanduser().resolve()
    try:
        timestamps = {
            commit.sha: int(run_git(repo, ["show", "-s", "--format=%ct", commit.sha]).strip())
            for commit in commits
        }
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        logger.warning("Unable to order selected commits in %s: %s", repo, exc)
        return None
    oldest = history_edge(
        repo,
        sorted(timestamps, key=lambda sha: timestamps[sha]),
        newest=False,
    )
    newest = history_edge(
        repo,
        sorted(timestamps, key=lambda sha: timestamps[sha], reverse=True),
        newest=True,
    )
    return oldest, newest


def materialized_repository_path(repository: RepositoryInput) -> Path | None:
    if repository.path or repository.local_path:
        return repository.path or repository.local_path
    if repository.repository_id:
        return RepositoryCacheService().cache_path(
            repository.project_id,
            repository.repository_id,
        )
    return None


def history_edge(repo: Path, candidates: list[str], *, newest: bool) -> str:
    if len(candidates) == 1:
        return candidates[0]
    for candidate in candidates:
        if all(is_history_edge(repo, candidate, other, newest=newest) for other in candidates):
            return candidate
    return candidates[0]


def is_history_edge(repo: Path, candidate: str, other: str, *, newest: bool) -> bool:
    if candidate == other:
        return True
    if newest:
        return is_ancestor(repo, other, candidate)
    return is_ancestor(repo, candidate, other)


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def parse_commit_log(
    repo: Path,
    repository: RepositoryInput,
    raw_log: str,
    warnings: list[str],
) -> list[CommitEvidence]:
    commits: list[CommitEvidence] = []
    context = CommitCollectionContext(repo, repository, warnings)
    max_commits = repository.max_commits or get_settings().model_evidence.max_commits
    for record in raw_log.split("\x1e"):
        if not record.strip():
            continue
        parts = record.split("\x1f", maxsplit=3)
        if len(parts) < 3:
            continue
        if len(parts) == 3:
            parts.append("")
        sha, date, subject, body = [part.strip() for part in parts]
        files = collect_commit_detail(
            collect_commit_files,
            context,
            sha,
            "file list",
        )
        file_stats = collect_commit_detail(
            collect_file_stats,
            context,
            sha,
            "file stats",
        )
        diff_hints = collect_commit_detail(
            collect_diff_hints,
            context,
            sha,
            "diff hints",
        )
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
        if len(commits) >= max_commits:
            break
    return commits


def collect_commit_detail[CommitDetailT](
    collector: Callable[[Path, str, list[str]], list[CommitDetailT]],
    context: CommitCollectionContext,
    sha: str,
    detail_name: str,
) -> list[CommitDetailT]:
    try:
        return collector(context.repo, sha, context.repository.paths)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or str(exc)).strip()
        context.warnings.append(
            f"{context.repository.name}: {detail_name} unavailable for {sha[:8]}: {detail}"
        )
        return []


def collect_cached_repository_evidence(
    repository: RepositoryInput,
) -> tuple[list[CommitEvidence], list[str]]:
    if repository.url is None:
        return [], [f"{repository.name}: repository URL is required"]
    service = RepositoryCacheService()
    project_repository = service.repository_from_input(repository)
    updated_repository = service.fetch(repository.project_id, project_repository)
    if updated_repository.cache_status.value == "failed":
        return [], [
            f"{repository.name}: local git collection failed: "
            f"{'; '.join(updated_repository.cache_warnings)}"
        ]
    if updated_repository.local_path is None:
        return [], [f"{repository.name}: local git collection failed: cache path unavailable"]

    repo_path = Path(updated_repository.local_path)
    warnings: list[str] = []
    branches = repository.branches or [repository.ref]
    if branches == ["HEAD"]:
        branches = [
            updated_repository.default_branch or service.default_branch(repo_path) or "main"
        ]

    commits: list[CommitEvidence] = []
    seen: set[str] = set()
    for branch in branches:
        branch_commits, branch_warnings = collect_cached_branch_evidence(
            repo_path,
            repository,
            branch,
        )
        warnings.extend(branch_warnings)
        for commit in branch_commits:
            if commit.sha in seen:
                continue
            seen.add(commit.sha)
            commits.append(commit)
    return commits, warnings


def collect_cached_branch_evidence(
    repo_path: Path,
    repository: RepositoryInput,
    branch: str,
) -> tuple[list[CommitEvidence], list[str]]:
    branch_ref = git_ref_candidates(branch)[0]
    base_ref = git_ref_candidates(repository.ref)[0]
    branch_repository = repository.model_copy(
        update={
            "path": repo_path,
            "local_path": repo_path,
            "url": None,
            "ref": branch_ref,
        }
    )
    revisions = [branch_ref]
    if not refs_resolve_to_same_commit(repo_path, branch_ref, base_ref):
        revisions.append(f"^{base_ref}")
    warnings: list[str] = []
    commits = collect_git_log_evidence(
        repo_path,
        branch_repository,
        revisions,
        warnings,
    )
    return commits, warnings


def refs_resolve_to_same_commit(repo: Path, left: str, right: str) -> bool:
    try:
        left_sha = run_git(repo, ["rev-parse", "--verify", left]).strip()
        right_sha = run_git(repo, ["rev-parse", "--verify", right]).strip()
    except subprocess.CalledProcessError:
        return False
    return left_sha == right_sha


def list_github_branches(url: str) -> tuple[list[dict[str, str | None]], str | None]:
    try:
        service = RepositoryCacheService()
        repository = service.repository_from_input(RepositoryInput(name="repository", url=url))
        _, branches, warning = service.list_branches("url-lookup", repository)
        return [branch.model_dump(mode="json") for branch in branches], warning
    except (subprocess.CalledProcessError, OSError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        logger.warning("Cached branch lookup failed for %s: %s", url, detail)
        return [], f"Local git branch lookup failed: {detail.strip()}"


def diff_hints_from_patch(file_path: str, patch: str) -> list[DiffHint]:
    hints: list[DiffHint] = []
    seen: set[str] = set()
    for line in patch.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        hint = meaningful_line(line[1:])
        if not hint or hint in seen:
            continue
        seen.add(hint)
        hints.append(DiffHint(file=file_path, hint=hint))
    return hints


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
    docs_input: list[tuple[str, Path | None, str | None, str | None]],
) -> tuple[list[DocumentationEvidence], list[str]]:
    docs: list[DocumentationEvidence] = []
    warnings: list[str] = []
    for name, path, description, content in docs_input:
        if content:
            docs.append(
                DocumentationEvidence(
                    name=name,
                    path=f"project-doc:{name}",
                    excerpt=f"{description or ''}\n{content[:4000]}".strip(),
                )
            )
            continue
        if path is None:
            warnings.append(f"{name}: documentation path or stored content is required")
            continue
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
        bundle.repositories.append(repository.url or str(repository.path))
        commits, warnings = collect_repository_evidence(repository)
        bundle.commits.extend(commits)
        bundle.warnings.extend(warnings)
    docs, doc_warnings = collect_documentation(
        [(doc.name, doc.path, doc.description, doc.content) for doc in documentation]
    )
    bundle.documentation.extend(docs)
    bundle.warnings.extend(doc_warnings)
    bundle.commits.sort(key=lambda commit: (commit.user_facing_score, commit.date), reverse=True)
    return bundle
