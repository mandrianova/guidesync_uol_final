from __future__ import annotations

from guidesync_agent.schemas import (
    BranchListResponse,
    ProjectConfig,
    ProjectCreate,
    ProjectRepository,
    RepositoryCacheStatus,
    RepositorySyncTask,
)
from guidesync_agent.services.repositories.cache import RepositoryCacheService
from guidesync_agent.services.repositories.tasks import RepositoryTaskQueue
from guidesync_agent.storage import create_project_store


class RepositoryProjectNotFoundError(ValueError):
    pass


class RepositoryNotFoundError(ValueError):
    pass


def sync_repository(project_id: str, repository_id: str) -> ProjectRepository:
    queue = RepositoryTaskQueue()
    if not queue.enabled:
        return sync_repository_now(project_id, repository_id)
    project, repository = project_repository(project_id, repository_id)
    updated = syncing_repository(project, repository)
    save_repository_state(project, updated)
    try:
        queue.send_repository_sync(
            RepositorySyncTask(project_id=project.id, repository_id=repository.id)
        )
    except Exception as exc:  # noqa: BLE001 - queue failures should be visible in project state
        updated = failed_repository_enqueue(updated, exc)
        save_repository_state(project, updated)
    return updated


def sync_repository_now(project_id: str, repository_id: str) -> ProjectRepository:
    project, repository = project_repository(project_id, repository_id)
    updated = RepositoryCacheService().clone_or_update(project.id, repository)
    save_repository_state(project, updated)
    return updated


def process_repository_sync_task(task: RepositorySyncTask) -> ProjectRepository:
    return sync_repository_now(task.project_id, task.repository_id)


def queue_project_repository_syncs(
    project: ProjectConfig,
    repository_ids: set[str] | None = None,
) -> ProjectConfig:
    queue = RepositoryTaskQueue()
    if not queue.enabled:
        return project
    if repository_ids is not None and not repository_ids:
        return project

    repositories: list[ProjectRepository] = []
    for repository in project.repositories:
        if repository_ids is not None and repository.id not in repository_ids:
            repositories.append(repository)
            continue
        if not repository.url.strip():
            repositories.append(repository)
            continue
        updated = syncing_repository(project, repository)
        try:
            queue.send_repository_sync(
                RepositorySyncTask(project_id=project.id, repository_id=repository.id)
            )
        except Exception as exc:  # noqa: BLE001 - persist queue errors for UI visibility
            updated = failed_repository_enqueue(updated, exc)
        repositories.append(updated)

    queued_project = project.model_copy(update={"repositories": repositories})
    return create_project_store().save(
        ProjectCreate.model_validate(queued_project.model_dump(mode="python")),
        project_id=project.id,
    )


def repository_status(project_id: str, repository_id: str) -> ProjectRepository:
    project, repository = project_repository(project_id, repository_id)
    updated = RepositoryCacheService().status(project.id, repository)
    save_repository_state(project, updated)
    return updated


def list_branches(project_id: str, repository_id: str) -> BranchListResponse:
    project, repository = project_repository(project_id, repository_id)
    updated, branches, warning = RepositoryCacheService().list_branches(project.id, repository)
    save_repository_state(project, updated)
    return BranchListResponse(branches=branches, warning=warning)


def project_repository(
    project_id: str,
    repository_id: str,
) -> tuple[ProjectConfig, ProjectRepository]:
    project = create_project_store().get(project_id)
    if project is None:
        raise RepositoryProjectNotFoundError(f"Project not found: {project_id}")
    repository = next((item for item in project.repositories if item.id == repository_id), None)
    if repository is None:
        raise RepositoryNotFoundError(f"Repository not found: {repository_id}")
    return project, repository


def save_repository_state(project: ProjectConfig, repository: ProjectRepository) -> ProjectConfig:
    updated_project = project.model_copy(
        update={
            "repositories": [
                repository if item.id == repository.id else item for item in project.repositories
            ]
        }
    )
    return create_project_store().save(
        ProjectCreate.model_validate(updated_project.model_dump(mode="python")),
        project_id=project.id,
    )


def syncing_repository(
    project: ProjectConfig,
    repository: ProjectRepository,
) -> ProjectRepository:
    return repository.model_copy(
        update={
            "cache_status": RepositoryCacheStatus.SYNCING,
            "local_path": str(RepositoryCacheService().cache_path(project.id, repository.id)),
            "cache_warnings": [],
        }
    )


def failed_repository_enqueue(
    repository: ProjectRepository,
    exc: Exception,
) -> ProjectRepository:
    return repository.model_copy(
        update={
            "cache_status": RepositoryCacheStatus.FAILED,
            "cache_warnings": [f"failed to enqueue repository sync: {exc}"],
        }
    )
