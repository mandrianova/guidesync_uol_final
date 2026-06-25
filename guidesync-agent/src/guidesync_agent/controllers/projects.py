from __future__ import annotations

from guidesync_agent.controllers.repositories import queue_project_repository_syncs
from guidesync_agent.schemas import ProjectConfig, ProjectCreate
from guidesync_agent.storage import create_project_store


def list_projects() -> list[ProjectConfig]:
    return create_project_store().list_projects()


def create_project(project: ProjectCreate) -> ProjectConfig:
    saved = create_project_store().save(project)
    return queue_project_repository_syncs(saved)


def get_project(project_id: str) -> ProjectConfig | None:
    return create_project_store().get(project_id)


def update_project(project_id: str, project: ProjectCreate) -> ProjectConfig | None:
    store = create_project_store()
    existing = store.get(project_id)
    if existing is None:
        return None
    saved = store.save(project, project_id=project_id)
    return queue_project_repository_syncs(
        saved,
        repository_ids=changed_repository_ids(existing, saved),
    )


def changed_repository_ids(previous: ProjectConfig, current: ProjectConfig) -> set[str]:
    previous_by_id = {repository.id: repository for repository in previous.repositories}
    changed: set[str] = set()
    for repository in current.repositories:
        previous_repository = previous_by_id.get(repository.id)
        if previous_repository is None:
            changed.add(repository.id)
            continue
        if (
            repository.url != previous_repository.url
            or repository.default_branch != previous_repository.default_branch
        ):
            changed.add(repository.id)
    return changed
