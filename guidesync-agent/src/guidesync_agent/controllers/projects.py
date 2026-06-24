from __future__ import annotations

from guidesync_agent.schemas import ProjectConfig, ProjectCreate
from guidesync_agent.storage import create_project_store


def list_projects() -> list[ProjectConfig]:
    return create_project_store().list_projects()


def create_project(project: ProjectCreate) -> ProjectConfig:
    return create_project_store().save(project)


def get_project(project_id: str) -> ProjectConfig | None:
    return create_project_store().get(project_id)


def update_project(project_id: str, project: ProjectCreate) -> ProjectConfig | None:
    store = create_project_store()
    if store.get(project_id) is None:
        return None
    return store.save(project, project_id=project_id)
