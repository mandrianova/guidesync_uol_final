from __future__ import annotations

from guidesync_agent.schemas import ProjectProfileSnapshot
from guidesync_agent.storage import create_project_profile_store


def get_project_profile(project_id: str) -> ProjectProfileSnapshot | None:
    return create_project_profile_store().latest(project_id)
