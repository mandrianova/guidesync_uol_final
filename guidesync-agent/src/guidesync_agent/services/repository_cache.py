from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
from pathlib import Path

from guidesync_agent.schemas import (
    ProjectRepository,
    RepositoryBranch,
    RepositoryCacheStatus,
    RepositoryInput,
)

logger = logging.getLogger(__name__)


class RepositoryCacheError(RuntimeError):
    pass


def repository_cache_root() -> Path:
    return Path(os.environ.get("GUIDESYNC_REPOSITORY_CACHE_DIR", "var/repositories"))


def run_git(repo: Path | None, args: list[str]) -> str:
    command = ["git", *args] if repo is None else ["git", "-C", str(repo), *args]
    logger.info("Running git command: %s", " ".join(command))
    completed = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def git_ref_candidates(ref: str) -> list[str]:
    if ref.startswith(("origin/", "refs/")) or re.fullmatch(r"[0-9a-fA-F]{7,40}", ref):
        return [ref]
    return [f"origin/{ref}", ref]


class RepositoryCacheService:
    def __init__(self, cache_root: Path | None = None) -> None:
        self.cache_root = cache_root or repository_cache_root()

    def clone_or_update(
        self,
        project_id: str | None,
        repository: ProjectRepository,
    ) -> ProjectRepository:
        repo_path = self.cache_path(project_id, repository.id)
        warnings: list[str] = []
        try:
            self._clone_or_fetch(repository.url, repo_path)
            default_branch = repository.default_branch or self.default_branch(repo_path)
            current_commit = self.current_commit(
                repo_path,
                f"origin/{default_branch}" if default_branch else None,
            )
            return repository.model_copy(
                update={
                    "default_branch": default_branch or repository.default_branch,
                    "cache_status": RepositoryCacheStatus.READY,
                    "local_path": str(repo_path),
                    "current_commit": current_commit,
                    "cache_warnings": warnings,
                }
            )
        except (OSError, subprocess.CalledProcessError, RepositoryCacheError) as exc:
            detail = git_error_detail(exc)
            logger.warning("Repository cache update failed for %s: %s", repository.url, detail)
            return repository.model_copy(
                update={
                    "cache_status": RepositoryCacheStatus.FAILED,
                    "local_path": str(repo_path),
                    "cache_warnings": [detail],
                }
            )

    def fetch(
        self,
        project_id: str | None,
        repository: ProjectRepository,
    ) -> ProjectRepository:
        return self.clone_or_update(project_id, repository)

    def pull_or_checkout_ref(
        self,
        project_id: str | None,
        repository: ProjectRepository,
        ref: str | None = None,
    ) -> ProjectRepository:
        updated = self.clone_or_update(project_id, repository)
        if updated.cache_status == RepositoryCacheStatus.FAILED:
            raise RepositoryCacheError(
                "; ".join(updated.cache_warnings) or "repository sync failed"
            )
        if updated.local_path is None:
            raise RepositoryCacheError("repository sync did not produce a local path")
        repo_path = Path(updated.local_path)
        checkout_ref = (ref or updated.default_branch or "HEAD").strip() or "HEAD"
        if checkout_ref == "HEAD":
            checkout_ref = updated.default_branch or self.default_branch(repo_path) or "main"

        last_error = ""
        for candidate in git_ref_candidates(checkout_ref):
            try:
                run_git(repo_path, ["rev-parse", "--verify", candidate])
                run_git(
                    repo_path,
                    [
                        "-c",
                        "filter.lfs.smudge=",
                        "-c",
                        "filter.lfs.process=",
                        "-c",
                        "filter.lfs.required=false",
                        "checkout",
                        "--force",
                        "--detach",
                        candidate,
                    ],
                )
                return updated.model_copy(
                    update={"current_commit": self.current_commit(repo_path, "HEAD")}
                )
            except subprocess.CalledProcessError as exc:
                last_error = exc.stderr.strip()
                continue
        message = f"git ref not found: {checkout_ref}"
        if last_error:
            message = f"{message} ({last_error})"
        raise RepositoryCacheError(message)

    def current_commit(self, repo_path: Path, ref: str | None = None) -> str | None:
        candidates = [item for item in [ref, "HEAD", "refs/remotes/origin/HEAD"] if item]
        for candidate in candidates:
            try:
                return run_git(repo_path, ["rev-parse", "--verify", candidate]).strip()
            except subprocess.CalledProcessError:
                continue
        return None

    def list_branches(
        self,
        project_id: str | None,
        repository: ProjectRepository,
    ) -> tuple[ProjectRepository, list[RepositoryBranch], str | None]:
        updated = self.clone_or_update(project_id, repository)
        if updated.cache_status == RepositoryCacheStatus.FAILED:
            return updated, [], "; ".join(updated.cache_warnings) or "Repository sync failed."
        if updated.local_path is None:
            return updated, [], "Repository sync did not produce a local path."

        raw = run_git(
            Path(updated.local_path),
            [
                "for-each-ref",
                "--format=%(refname:short)%09%(committerdate:iso8601)",
                "refs/remotes/origin",
            ],
        )
        branches = []
        for line in raw.splitlines():
            ref, _, updated_at = line.partition("\t")
            branch_name = ref.strip().removeprefix("origin/")
            if not branch_name or ref.strip() == "origin/HEAD" or branch_name == "origin":
                continue
            branches.append(
                RepositoryBranch(name=branch_name, updated_at=updated_at.strip() or None)
            )
        branches.sort(key=lambda branch: branch.name)
        if branches:
            return updated, branches, None
        return updated, [], "No branches were found in the local repository cache."

    def list_files(
        self,
        project_id: str | None,
        repository: ProjectRepository,
        ref: str | None = None,
        paths: list[str] | None = None,
    ) -> tuple[ProjectRepository, list[str]]:
        updated = self.clone_or_update(project_id, repository)
        if updated.cache_status == RepositoryCacheStatus.FAILED:
            raise RepositoryCacheError(
                "; ".join(updated.cache_warnings) or "repository sync failed"
            )
        if updated.local_path is None:
            raise RepositoryCacheError("repository sync did not produce a local path")
        target_ref = ref or updated.default_branch or "HEAD"
        if target_ref == "HEAD":
            target_ref = (
                updated.default_branch
                or self.default_branch(Path(updated.local_path))
                or "main"
            )
        args = ["ls-tree", "-r", "--name-only", *git_ref_candidates(target_ref)[:1]]
        if paths:
            args.extend(["--", *paths])
        raw = run_git(Path(updated.local_path), args)
        return updated, [line.strip() for line in raw.splitlines() if line.strip()]

    def status(self, project_id: str | None, repository: ProjectRepository) -> ProjectRepository:
        repo_path = self.cache_path(project_id, repository.id)
        if not (repo_path / ".git").exists():
            return repository.model_copy(
                update={
                    "cache_status": RepositoryCacheStatus.NOT_SYNCED,
                    "local_path": str(repo_path),
                    "current_commit": None,
                }
            )
        return repository.model_copy(
            update={
                "cache_status": RepositoryCacheStatus.READY,
                "local_path": str(repo_path),
                "current_commit": self.current_commit(repo_path),
            }
        )

    def repository_from_input(self, repository: RepositoryInput) -> ProjectRepository:
        repository_id = repository.repository_id or stable_cache_id(
            repository.url or repository.name,
            "repo",
        )
        default_branch = repository.ref
        if (
            repository.ref == "HEAD"
            or repository.ref.startswith(("origin/", "refs/"))
            or re.fullmatch(r"[0-9a-fA-F]{7,40}", repository.ref)
        ):
            default_branch = None
        return ProjectRepository(
            id=repository_id,
            name=repository.name,
            url=repository.url or "",
            default_branch=default_branch,
            analysis_paths=repository.paths,
            local_path=str(repository.local_path) if repository.local_path else None,
        )

    def cache_path(self, project_id: str | None, repository_id: str) -> Path:
        return (
            self.cache_root
            / safe_cache_component(project_id or "standalone")
            / safe_cache_component(repository_id)
        )

    def default_branch(self, repo_path: Path) -> str | None:
        try:
            raw = run_git(repo_path, ["symbolic-ref", "refs/remotes/origin/HEAD"])
        except subprocess.CalledProcessError as exc:
            logger.info("origin/HEAD is unavailable, trying remote set-head: %s", exc.stderr)
            try:
                run_git(repo_path, ["remote", "set-head", "origin", "--auto"])
                raw = run_git(repo_path, ["symbolic-ref", "refs/remotes/origin/HEAD"])
            except subprocess.CalledProcessError:
                return self.first_remote_branch(repo_path)
        branch = raw.strip().removeprefix("refs/remotes/origin/")
        return branch or self.first_remote_branch(repo_path)

    def first_remote_branch(self, repo_path: Path) -> str | None:
        try:
            raw = run_git(
                repo_path,
                ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"],
            )
        except subprocess.CalledProcessError:
            return None
        for line in raw.splitlines():
            branch = line.strip().removeprefix("origin/")
            if branch and branch != "HEAD":
                return branch
        return None

    def _clone_or_fetch(self, url: str, repo_path: Path) -> None:
        if not url.strip():
            raise RepositoryCacheError("repository clone URL is required")
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        if (repo_path / ".git").exists():
            run_git(repo_path, ["remote", "set-url", "origin", url])
        elif repo_path.exists() and any(repo_path.iterdir()):
            raise RepositoryCacheError(
                f"cache path exists and is not a git repository: {repo_path}"
            )
        else:
            run_git(
                None,
                [
                    "clone",
                    "--filter=blob:none",
                    "--no-checkout",
                    url,
                    str(repo_path),
                ],
            )
        run_git(
            repo_path,
            [
                "fetch",
                "--prune",
                "origin",
                "+refs/heads/*:refs/remotes/origin/*",
            ],
        )


def safe_cache_component(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"{(slug or 'item')[:50]}-{digest}"


def stable_cache_id(value: str, prefix: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")[:40] or prefix
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{slug}-{digest}"


def git_error_detail(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr.strip()
        stdout = exc.stdout.strip()
        return stderr or stdout or f"git exited with status {exc.returncode}"
    return str(exc)
