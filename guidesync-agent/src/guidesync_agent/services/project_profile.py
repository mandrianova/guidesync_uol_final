from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from guidesync_agent.knowledge_tagging import tokenize_text
from guidesync_agent.schemas import (
    ProjectConfig,
    ProjectProfileRepositoryMapItem,
    ProjectProfileSnapshot,
    ProjectProfileSourceRef,
    ProjectProfileStatus,
    ProjectProfileTask,
    ProjectRepository,
    RepositoryCacheStatus,
)
from guidesync_agent.services.repository_cache import RepositoryCacheService
from guidesync_agent.services.repository_tasks import RepositoryTaskQueue
from guidesync_agent.storage import create_project_profile_store, create_project_store

PROJECT_PROFILE_PROMPT_VERSION = "project-profile-analyzer-v1"
DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
MAX_PROFILE_DOCS = 25
MAX_PROFILE_FILE_BYTES = 120_000

ARCHITECTURE_TERMS = {
    "architecture",
    "component",
    "components",
    "design",
    "pipeline",
    "service",
    "system",
}
WORKFLOW_TERMS = {
    "deploy",
    "deployment",
    "guide",
    "run",
    "setup",
    "test",
    "usage",
    "workflow",
}
STOP_TERMS = {
    "about",
    "after",
    "and",
    "are",
    "before",
    "from",
    "guide",
    "into",
    "not",
    "project",
    "that",
    "the",
    "this",
    "with",
}


def queue_project_profile_build(
    project: ProjectConfig,
    *,
    reason: str,
) -> ProjectProfileSnapshot:
    queue = RepositoryTaskQueue()
    if not queue.enabled:
        return build_project_profile_for_project(project, reason=reason)

    store = create_project_profile_store()
    profile = empty_project_profile(project, ProjectProfileStatus.QUEUED, reason=reason)
    store.save(profile)
    try:
        queue.send_project_profile(
            ProjectProfileTask(project_id=project.id, profile_id=profile.id, reason=reason)
        )
    except Exception as exc:  # noqa: BLE001 - persist queue failure for API/UI visibility
        profile = profile.model_copy(
            update={
                "status": ProjectProfileStatus.FAILED,
                "completed_at": datetime.now(UTC),
                "error_message": f"failed to enqueue project profile task: {exc}",
                "warnings": [f"failed to enqueue project profile task: {exc}"],
            }
        )
        store.save(profile)
    return profile


def process_project_profile_task(task: ProjectProfileTask) -> ProjectProfileSnapshot | None:
    return build_project_profile(task.project_id, profile_id=task.profile_id, reason=task.reason)


def build_project_profile(
    project_id: str,
    *,
    profile_id: str | None = None,
    reason: str = "manual",
) -> ProjectProfileSnapshot | None:
    project = create_project_store().get(project_id)
    if project is None:
        return None
    return build_project_profile_for_project(project, profile_id=profile_id, reason=reason)


def build_project_profile_for_project(
    project: ProjectConfig,
    *,
    profile_id: str | None = None,
    reason: str = "manual",
) -> ProjectProfileSnapshot:
    store = create_project_profile_store()
    existing = store.get(profile_id) if profile_id else None
    created_at = existing.created_at if existing else datetime.now(UTC)
    version = existing.version if existing else next_project_profile_version(project.id)
    running = empty_project_profile(
        project,
        ProjectProfileStatus.RUNNING,
        profile_id=profile_id or (existing.id if existing else None),
        version=version,
        created_at=created_at,
        reason=reason,
    )
    store.save(running)
    try:
        profile = analyze_project_profile(project, running)
        profile = write_project_profile_artifacts(project, profile)
        return store.save(profile)
    except Exception as exc:  # noqa: BLE001 - keep failed profile visible for diagnostics
        failed = running.model_copy(
            update={
                "status": ProjectProfileStatus.FAILED,
                "completed_at": datetime.now(UTC),
                "error_message": str(exc),
                "warnings": [*running.warnings, str(exc)],
            }
        )
        return store.save(failed)


def latest_project_profile(project_id: str) -> ProjectProfileSnapshot | None:
    return create_project_profile_store().latest(project_id)


def list_project_profiles(project_id: str) -> list[ProjectProfileSnapshot]:
    return create_project_profile_store().list_profiles(project_id)


def project_profile_rebuild_needed(
    previous: ProjectConfig,
    current: ProjectConfig,
) -> bool:
    return project_profile_fingerprint(previous) != project_profile_fingerprint(current)


def project_profile_fingerprint(project: ProjectConfig) -> dict[str, object]:
    return {
        "name": project.name,
        "description": project.description,
        "audience": project.audience.value,
        "documentation_instructions": project.documentation_instructions,
        "knowledge_base_repository_id": project.knowledge_base_repository_id,
        "knowledge_base_ref": project.knowledge_base_ref,
        "knowledge_base_path": project.knowledge_base_path,
        "analysis_paths": project.analysis_paths,
        "repositories": [
            {
                "id": repository.id,
                "name": repository.name,
                "url": repository.url,
                "default_branch": repository.default_branch,
                "analysis_paths": repository.analysis_paths,
                "credential_ref": repository.credential_ref,
            }
            for repository in project.repositories
        ],
    }


def empty_project_profile(
    project: ProjectConfig,
    status: ProjectProfileStatus,
    *,
    profile_id: str | None = None,
    version: int | None = None,
    created_at: datetime | None = None,
    reason: str,
) -> ProjectProfileSnapshot:
    return ProjectProfileSnapshot(
        id=profile_id or f"profile-{uuid4().hex[:10]}",
        project_id=project.id,
        status=status,
        version=version or next_project_profile_version(project.id),
        prompt_version=PROJECT_PROFILE_PROMPT_VERSION,
        summary=f"Project profile build {status.value}: {reason}.",
        warnings=[],
        uncertainty_notes=[],
        created_at=created_at or datetime.now(UTC),
    )


def next_project_profile_version(project_id: str) -> int:
    latest = create_project_profile_store().latest(project_id)
    return 1 if latest is None else latest.version + 1


def analyze_project_profile(
    project: ProjectConfig,
    base_profile: ProjectProfileSnapshot,
) -> ProjectProfileSnapshot:
    repository_data = [
        inspect_repository(project, repository) for repository in project.repositories
    ]
    repository_map = [item[0] for item in repository_data]
    source_refs = [item[1] for item in repository_data]
    warnings = [warning for item in repository_data for warning in item[2]]
    docs = load_profile_documents(project, repository_data)
    warnings.extend(docs.warnings)
    architecture = summarize_architecture(project, repository_map, docs)
    workflows = summarize_workflows(project, docs)
    key_terms = extract_key_terms(project, docs, repository_map)
    uncertainty_notes = uncertainty_notes_for(project, docs, warnings)
    return base_profile.model_copy(
        update={
            "status": ProjectProfileStatus.COMPLETED,
            "summary": summarize_project(project, docs),
            "architecture": architecture,
            "workflows": workflows,
            "key_terms": key_terms,
            "repository_map": repository_map,
            "source_refs": source_refs,
            "warnings": warnings,
            "uncertainty_notes": uncertainty_notes,
            "completed_at": datetime.now(UTC),
            "error_message": None,
        }
    )


def inspect_repository(
    project: ProjectConfig,
    repository: ProjectRepository,
) -> tuple[ProjectProfileRepositoryMapItem, ProjectProfileSourceRef, list[str]]:
    cache_service = RepositoryCacheService()
    status_repository = cache_service.status(project.id, repository)
    local_path = status_repository.local_path
    current_commit = status_repository.current_commit
    cache_status = status_repository.cache_status
    direct_path = direct_local_repository_path(repository)
    if cache_status != RepositoryCacheStatus.READY and direct_path is not None:
        local_path = str(direct_path)
        current_commit = cache_service.current_commit(direct_path)
        cache_status = RepositoryCacheStatus.READY
    knowledge_base_path = (
        normalized_profile_path(project.knowledge_base_path)
        if repository.id == selected_knowledge_repository_id(project)
        else None
    )
    warnings = list(status_repository.cache_warnings)
    if cache_status != RepositoryCacheStatus.READY:
        warnings.append(f"repository cache is not ready for {repository.name}")
    source_ref = ProjectProfileSourceRef(
        repository_id=repository.id,
        repository_name=repository.name,
        ref=project.knowledge_base_ref or repository.default_branch,
        commit_sha=current_commit,
        local_path=local_path,
        docs_path=knowledge_base_path,
        analysis_paths=repository.analysis_paths or project.analysis_paths,
    )
    repository_map = ProjectProfileRepositoryMapItem(
        repository_id=repository.id,
        name=repository.name,
        url=repository.url,
        default_branch=repository.default_branch,
        current_commit=current_commit,
        cache_status=cache_status,
        analysis_paths=repository.analysis_paths or project.analysis_paths,
        knowledge_base_path=knowledge_base_path,
    )
    return repository_map, source_ref, warnings


def direct_local_repository_path(repository: ProjectRepository) -> Path | None:
    if "://" in repository.url or not repository.url:
        return None
    candidate = Path(repository.url).expanduser()
    if not candidate.exists():
        return None
    return candidate.resolve()


def selected_knowledge_repository_id(project: ProjectConfig) -> str | None:
    if project.knowledge_base_repository_id:
        return project.knowledge_base_repository_id
    return project.repositories[0].id if project.repositories else None


def normalized_profile_path(path: str | None) -> str:
    value = (path or "docs/").strip().lstrip("/")
    return value or "docs/"


class ProfileDocuments:
    def __init__(
        self,
        *,
        files: list[str],
        headings: list[str],
        warnings: list[str],
    ) -> None:
        self.files = files
        self.headings = headings
        self.warnings = warnings


def load_profile_documents(
    project: ProjectConfig,
    repository_data: list[
        tuple[ProjectProfileRepositoryMapItem, ProjectProfileSourceRef, list[str]]
    ],
) -> ProfileDocuments:
    selected_repository_id = selected_knowledge_repository_id(project)
    source = next(
        (
            source_ref
            for _, source_ref, _ in repository_data
            if source_ref.repository_id == selected_repository_id
        ),
        None,
    )
    if source is None or source.local_path is None:
        return ProfileDocuments(
            files=[],
            headings=[],
            warnings=["knowledge base repository is not available for profile analysis"],
        )

    repo_root = Path(source.local_path).resolve()
    docs_root = safe_child_path(repo_root, source.docs_path or project.knowledge_base_path)
    if docs_root is None:
        return ProfileDocuments(
            files=[],
            headings=[],
            warnings=["knowledge base path is outside the repository"],
        )
    if not docs_root.exists():
        return ProfileDocuments(
            files=[],
            headings=[],
            warnings=[f"knowledge base path does not exist: {source.docs_path}"],
        )

    files: list[str] = []
    headings: list[str] = []
    warnings: list[str] = []
    for path in sorted(docs_root.rglob("*")):
        if len(files) >= MAX_PROFILE_DOCS:
            warnings.append(f"profile document scan stopped after {MAX_PROFILE_DOCS} files")
            break
        if not path.is_file() or path.suffix.lower() not in DOC_SUFFIXES:
            continue
        relative_path = path.relative_to(repo_root).as_posix()
        files.append(relative_path)
        try:
            if path.stat().st_size > MAX_PROFILE_FILE_BYTES:
                warnings.append(f"profile skipped large document: {relative_path}")
                continue
            headings.extend(markdown_headings(path.read_text(encoding="utf-8")))
        except OSError as exc:
            warnings.append(f"profile could not read {relative_path}: {exc}")
        except UnicodeDecodeError:
            warnings.append(f"profile skipped non-text document: {relative_path}")
    if not files:
        warnings.append(f"no profile documents found under {source.docs_path}")
    return ProfileDocuments(files=files, headings=headings, warnings=warnings)


def safe_child_path(root: Path, relative_path: str | None) -> Path | None:
    root_resolved = root.resolve()
    candidate = (root_resolved / normalized_profile_path(relative_path)).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def markdown_headings(text: str) -> list[str]:
    headings: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if match:
            headings.append(match.group(1).strip(" #"))
    return headings


def summarize_project(project: ProjectConfig, docs: ProfileDocuments) -> str:
    base = project.description or (
        f"{project.name} is configured for {project.audience.value.replace('_', ' ')} "
        "documentation updates."
    )
    docs_summary = (
        f" The baseline profile scanned {len(docs.files)} documentation files."
        if docs.files
        else " The baseline profile did not find readable documentation files yet."
    )
    return f"{base.strip()}{docs_summary}"


def summarize_architecture(
    project: ProjectConfig,
    repository_map: list[ProjectProfileRepositoryMapItem],
    docs: ProfileDocuments,
) -> list[str]:
    architecture = filtered_headings(docs.headings, ARCHITECTURE_TERMS)
    if architecture:
        return architecture[:8]
    repositories = ", ".join(item.name for item in repository_map) or "no repositories"
    analysis_paths = ", ".join(project.analysis_paths) or "repository defaults"
    return [
        f"Repositories: {repositories}.",
        f"Knowledge base path: {project.knowledge_base_path or 'docs/'}.",
        f"Analysis paths: {analysis_paths}.",
    ]


def summarize_workflows(project: ProjectConfig, docs: ProfileDocuments) -> list[str]:
    workflows = filtered_headings(docs.headings, WORKFLOW_TERMS)
    if workflows:
        return workflows[:8]
    if project.documentation_instructions:
        return [project.documentation_instructions]
    return [
        "Documentation update runs should start from repository evidence "
        "and saved project settings."
    ]


def filtered_headings(headings: list[str], terms: set[str]) -> list[str]:
    matches = []
    seen: set[str] = set()
    for heading in headings:
        normalized = heading.lower()
        if normalized in seen:
            continue
        if any(term in tokenize_text(heading) or term in normalized for term in terms):
            matches.append(heading)
            seen.add(normalized)
    return matches


def extract_key_terms(
    project: ProjectConfig,
    docs: ProfileDocuments,
    repository_map: list[ProjectProfileRepositoryMapItem],
) -> list[str]:
    text = " ".join(
        [
            project.name,
            project.description or "",
            project.documentation_instructions,
            " ".join(docs.headings),
            " ".join(docs.files),
            " ".join(repository.name for repository in repository_map),
        ]
    )
    counts = Counter(
        term for term in tokenize_text(text) if term not in STOP_TERMS and len(term) > 2
    )
    return [term for term, _ in counts.most_common(16)]


def uncertainty_notes_for(
    project: ProjectConfig,
    docs: ProfileDocuments,
    warnings: list[str],
) -> list[str]:
    notes = [
        "Profile is generated from saved project settings and locally cached repository documents.",
    ]
    if warnings:
        notes.append(
            "Some source evidence was unavailable; see warnings before relying on this profile."
        )
    if not project.description:
        notes.append(
            "Project description is empty, so summary quality depends on repository documentation."
        )
    if not docs.headings:
        notes.append(
            "No documentation headings were available for architecture/workflow extraction."
        )
    return notes


def write_project_profile_artifacts(
    project: ProjectConfig,
    profile: ProjectProfileSnapshot,
) -> ProjectProfileSnapshot:
    output_dir = project_profile_output_dir() / project.id / profile.id
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "profile.json"
    markdown_path = output_dir / "profile.md"
    profile_with_artifacts = profile.model_copy(
        update={
            "artifact_uris": {
                "profile.json": str(json_path),
                "profile.md": str(markdown_path),
            }
        }
    )
    json_path.write_text(
        json.dumps(profile_with_artifacts.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        project_profile_markdown(project, profile_with_artifacts),
        encoding="utf-8",
    )
    return profile_with_artifacts


def project_profile_output_dir() -> Path:
    return Path(os.environ.get("GUIDESYNC_PROJECT_PROFILE_OUTPUT_DIR", "outputs/project-profiles"))


def project_profile_markdown(project: ProjectConfig, profile: ProjectProfileSnapshot) -> str:
    sections = [
        f"# Project Profile: {project.name}",
        f"Profile id: `{profile.id}`",
        f"Version: `{profile.version}`",
        f"Prompt version: `{profile.prompt_version}`",
        "",
        "## Summary",
        profile.summary,
        "",
        markdown_list("Architecture", profile.architecture),
        markdown_list("Workflows", profile.workflows),
        markdown_list("Key terms", profile.key_terms),
        markdown_repository_map(profile.repository_map),
        markdown_list("Warnings", profile.warnings),
        markdown_list("Uncertainty notes", profile.uncertainty_notes),
    ]
    return "\n".join(sections).rstrip() + "\n"


def markdown_list(title: str, items: list[str]) -> str:
    lines = [f"## {title}"]
    lines.extend(f"- {item}" for item in items)
    if len(lines) == 1:
        lines.append("- None recorded.")
    return "\n".join(lines)


def markdown_repository_map(repository_map: list[ProjectProfileRepositoryMapItem]) -> str:
    lines = ["## Repository map"]
    if not repository_map:
        lines.append("- None configured.")
        return "\n".join(lines)
    for repository in repository_map:
        commit = repository.current_commit or "unknown commit"
        lines.append(
            f"- `{repository.repository_id}` {repository.name}: "
            f"{repository.default_branch or 'default ref'} at {commit}"
        )
    return "\n".join(lines)
