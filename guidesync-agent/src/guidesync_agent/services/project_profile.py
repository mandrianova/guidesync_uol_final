from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

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
from guidesync_agent.services.project_profile_agent import (
    ProjectProfileAgentError,
    ProjectProfileRepositoryData,
    run_project_profile_agent,
)
from guidesync_agent.services.project_profile_artifacts import write_project_profile_artifacts
from guidesync_agent.services.project_profile_sources import normalized_profile_path
from guidesync_agent.services.repository_cache import RepositoryCacheService
from guidesync_agent.services.repository_tasks import RepositoryTaskQueue
from guidesync_agent.storage import create_project_profile_store, create_project_store

PROJECT_PROFILE_PROMPT_VERSION = "project-profile-analyzer-v2"


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
        profile = analyze_project_profile(project, running, reason=reason)
        profile = write_project_profile_artifacts(project, profile)
        return store.save(profile)
    except Exception as exc:  # noqa: BLE001 - keep failed profile visible for diagnostics
        validation_findings = (
            exc.validation_findings if isinstance(exc, ProjectProfileAgentError) else []
        )
        failed = running.model_copy(
            update={
                "status": ProjectProfileStatus.FAILED,
                "completed_at": datetime.now(UTC),
                "error_message": str(exc),
                "warnings": [*running.warnings, str(exc)],
                "validation_findings": validation_findings,
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
    *,
    reason: str = "manual",
) -> ProjectProfileSnapshot:
    repository_data = [
        inspect_repository(project, repository) for repository in project.repositories
    ]
    repository_map = [item[0] for item in repository_data]
    source_refs = [item[1] for item in repository_data]
    warnings = [warning for item in repository_data for warning in item[2]]
    agent_result = run_project_profile_agent(
        project,
        base_profile,
        [
            ProjectProfileRepositoryData(
                repository_map=item[0],
                source_ref=item[1],
                warnings=item[2],
            )
            for item in repository_data
        ],
        reason=reason,
    )
    output = agent_result.output
    taxonomy = output.taxonomy.model_copy(
        update={"version": output.taxonomy.version or f"{base_profile.id}:v{base_profile.version}"}
    )
    tool_trace_refs = [
        f"project-profile-tool:{index}:{trace.tool_name}:{trace.repository_id or 'project'}"
        for index, trace in enumerate(agent_result.evidence.tool_trace, start=1)
    ]
    return base_profile.model_copy(
        update={
            "status": ProjectProfileStatus.COMPLETED,
            "summary": output.summary,
            "architecture": output.architecture,
            "workflows": output.workflows,
            "key_terms": output.key_terms,
            "taxonomy": taxonomy,
            "profile_evidence": output.profile_evidence,
            "repository_map": output.repository_map or repository_map,
            "source_refs": output.source_refs or source_refs,
            "warnings": [*warnings, *output.warnings, *agent_result.selection.warnings],
            "uncertainty_notes": output.uncertainty_notes,
            "model_metadata": {
                **agent_result.model_metadata,
                "selection": agent_result.selection.model_dump(mode="json"),
                "tool_trace": [
                    trace.model_dump(mode="json") for trace in agent_result.evidence.tool_trace
                ],
            },
            "tool_trace_refs": tool_trace_refs,
            "validation_findings": agent_result.validation_findings,
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
