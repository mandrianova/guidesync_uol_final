from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

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
    if repository.url:
        return collect_github_repository_evidence(repository)
    if repository.path is None:
        return [], [f"{repository.name}: repository path or URL is required"]
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
        if repository.max_commits is not None and len(commits) >= repository.max_commits:
            break
    return commits, warnings


def github_owner_repo(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if parsed.netloc not in {"github.com", "www.github.com"}:
        return None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None
    return parts[0], parts[1].removesuffix(".git")


def github_api_get(path: str, query: dict[str, str] | None = None) -> tuple[object, dict[str, str]]:
    url = f"https://api.github.com{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "guidesync-agent-prototype",
        },
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
        return payload, dict(response.headers.items())


def collect_github_repository_evidence(
    repository: RepositoryInput,
) -> tuple[list[CommitEvidence], list[str]]:
    if repository.url is None:
        return [], [f"{repository.name}: GitHub URL is required"]
    owner_repo = github_owner_repo(repository.url)
    if owner_repo is None:
        return [], [f"{repository.name}: only public GitHub repository URLs are supported for now"]
    owner, repo = owner_repo
    warnings: list[str] = []
    branches = repository.branches or [repository.ref]
    if branches == ["HEAD"]:
        default_branch, default_warning = github_default_branch(owner, repo)
        if default_warning:
            warnings.append(f"{repository.name}: {default_warning}")
        branches = [default_branch or "main"]

    commits: list[CommitEvidence] = []
    seen: set[str] = set()
    for branch in branches:
        branch_commits, branch_warnings = collect_github_branch_commits(
            repository, owner, repo, branch
        )
        warnings.extend(branch_warnings)
        for commit in branch_commits:
            if commit.sha in seen:
                continue
            seen.add(commit.sha)
            commits.append(commit)
    return commits, warnings


def github_default_branch(owner: str, repo: str) -> tuple[str | None, str | None]:
    try:
        payload, _ = github_api_get(f"/repos/{owner}/{repo}")
    except (HTTPError, URLError, TimeoutError) as exc:
        return None, f"failed to load default branch from GitHub: {exc}"
    if not isinstance(payload, dict):
        return None, "unexpected GitHub repository response"
    default_branch = payload.get("default_branch")
    return default_branch if isinstance(default_branch, str) else None, None


def list_github_branches(url: str) -> tuple[list[str], str | None]:
    owner_repo = github_owner_repo(url)
    if owner_repo is None:
        return [], "Only public GitHub repository URLs are supported for branch lookup."
    owner, repo = owner_repo
    branches: list[str] = []
    page = 1
    while True:
        try:
            payload, headers = github_api_get(
                f"/repos/{owner}/{repo}/branches",
                {"per_page": "100", "page": str(page)},
            )
        except (HTTPError, URLError, TimeoutError) as exc:
            return branches, f"GitHub branches request failed: {exc}"
        if not isinstance(payload, list):
            return branches, "Unexpected GitHub branches response."
        if not payload:
            break
        for item in payload:
            if not isinstance(item, dict):
                continue
            branch_name = item.get("name")
            if isinstance(branch_name, str):
                branches.append(branch_name)
        if 'rel="next"' not in headers.get("Link", ""):
            break
        page += 1
    return branches, None


def collect_github_branch_commits(
    repository: RepositoryInput,
    owner: str,
    repo: str,
    branch: str,
) -> tuple[list[CommitEvidence], list[str]]:
    warnings: list[str] = []
    commits: list[CommitEvidence] = []
    page = 1
    while True:
        query = {"sha": branch, "per_page": "100", "page": str(page)}
        since = github_datetime(repository.since)
        if since:
            query["since"] = since
        until = github_datetime(repository.until)
        if until:
            query["until"] = until
        try:
            payload, headers = github_api_get(f"/repos/{owner}/{repo}/commits", query)
        except (HTTPError, URLError, TimeoutError) as exc:
            return commits, [f"{repository.name}/{branch}: GitHub commits request failed: {exc}"]
        if not isinstance(payload, list):
            return commits, [f"{repository.name}/{branch}: unexpected GitHub commits response"]
        if not payload:
            break
        for item in payload:
            if not isinstance(item, dict):
                continue
            sha = str(item.get("sha", ""))
            if not sha:
                continue
            commit = github_commit_detail(repository, owner, repo, sha)
            if commit is None:
                warnings.append(f"{repository.name}/{branch}: failed to load commit {sha[:8]}")
                continue
            commits.append(commit)
        if 'rel="next"' not in headers.get("Link", ""):
            break
        page += 1
    return commits, warnings


def github_datetime(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    if stripped in {"30 days ago", "HEAD"}:
        return None
    try:
        parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
    except ValueError:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stripped):
            return f"{stripped}T00:00:00Z"
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def github_commit_detail(
    repository: RepositoryInput,
    owner: str,
    repo: str,
    sha: str,
) -> CommitEvidence | None:
    try:
        payload, _ = github_api_get(f"/repos/{owner}/{repo}/commits/{sha}")
    except (HTTPError, URLError, TimeoutError):
        return None
    if not isinstance(payload, dict):
        return None
    commit_info = payload.get("commit")
    if not isinstance(commit_info, dict):
        return None
    message = str(commit_info.get("message", ""))
    subject, _, body = message.partition("\n")
    author = commit_info.get("author")
    date = ""
    if isinstance(author, dict):
        date = str(author.get("date", ""))[:10]
    files_payload = payload.get("files")
    files: list[str] = []
    file_stats: list[FileChange] = []
    diff_hints: list[DiffHint] = []
    if isinstance(files_payload, list):
        for file_item in files_payload:
            if not isinstance(file_item, dict):
                continue
            file_path = str(file_item.get("filename", ""))
            if repository.paths and not any(
                file_path.startswith(path) for path in repository.paths
            ):
                continue
            files.append(file_path)
            file_stats.append(
                FileChange(
                    file=file_path,
                    added=github_int(file_item.get("additions")),
                    removed=github_int(file_item.get("deletions")),
                )
            )
            patch = file_item.get("patch")
            if isinstance(patch, str):
                diff_hints.extend(diff_hints_from_patch(file_path, patch))
    return CommitEvidence(
        repo=repository.name,
        sha=sha,
        short_sha=sha[:8],
        date=date,
        subject=subject.strip(),
        body=body.strip(),
        files=files,
        file_stats=file_stats,
        diff_hints=diff_hints[:20],
        user_facing_score=score_commit(subject, body, files, diff_hints),
    )


def github_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


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
