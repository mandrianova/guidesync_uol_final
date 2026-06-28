from __future__ import annotations

from typing import Any

from guidesync_agent.schemas import ProjectProfileSnapshot
from guidesync_agent.storage import create_project_profile_store


def get_project_profile(project_id: str) -> ProjectProfileSnapshot | None:
    return create_project_profile_store().latest(project_id)


def register_project_profile_tool(agent: Any) -> None:
    @agent.tool
    def get_project_profile_tool(project_id: str) -> dict[str, object]:
        profile = get_project_profile(project_id)
        if profile is None:
            return {
                "ok": False,
                "error": f"Project profile not found for project: {project_id}",
            }
        return {"ok": True, "profile": profile.model_dump(mode="json")}
