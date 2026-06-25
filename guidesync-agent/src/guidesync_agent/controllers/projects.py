from __future__ import annotations

from guidesync_agent.controllers.repositories import queue_project_repository_syncs
from guidesync_agent.schemas import ProjectConfig, ProjectCreate, ProjectProfileSnapshot
from guidesync_agent.services.project_profile import (
    latest_project_profile,
    list_project_profiles,
    project_profile_rebuild_needed,
    queue_project_profile_build,
)
from guidesync_agent.storage import create_project_store


def list_projects() -> list[ProjectConfig]:
    return create_project_store().list_projects()


def create_project(project: ProjectCreate) -> ProjectConfig:
    saved = create_project_store().save(project)
    queued = queue_project_repository_syncs(saved)
    queue_project_profile_build(queued, reason="project_created")
    return queued


def get_project(project_id: str) -> ProjectConfig | None:
    return create_project_store().get(project_id)


def update_project(project_id: str, project: ProjectCreate) -> ProjectConfig | None:
    store = create_project_store()
    existing = store.get(project_id)
    if existing is None:
        return None
    saved = store.save(project, project_id=project_id)
    queued = queue_project_repository_syncs(
        saved,
        repository_ids=changed_repository_ids(existing, saved),
    )
    if project_profile_rebuild_needed(existing, queued):
        queue_project_profile_build(queued, reason="project_updated")
    return queued


def get_latest_project_profile(project_id: str) -> ProjectProfileSnapshot | None:
    if create_project_store().get(project_id) is None:
        return None
    return latest_project_profile(project_id)


def get_project_profiles(project_id: str) -> list[ProjectProfileSnapshot] | None:
    if create_project_store().get(project_id) is None:
        return None
    return list_project_profiles(project_id)


def rebuild_project_profile(project_id: str) -> ProjectProfileSnapshot | None:
    project = create_project_store().get(project_id)
    if project is None:
        return None
    return queue_project_profile_build(project, reason="manual_rebuild")


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
