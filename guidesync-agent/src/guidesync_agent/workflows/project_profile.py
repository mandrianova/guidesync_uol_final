from __future__ import annotations

from guidesync_agent.schemas import ProjectProfileSnapshot, ProjectProfileTask
from guidesync_agent.services.project_profile import (
    build_project_profile,
    process_project_profile_task,
)


def run_project_profile_workflow(
    task: ProjectProfileTask,
) -> ProjectProfileSnapshot | None:
    return process_project_profile_task(task)


def rebuild_project_profile(
    project_id: str,
    *,
    profile_id: str | None = None,
    reason: str = "manual",
    workflow_task_id: str | None = None,
) -> ProjectProfileSnapshot | None:
    return build_project_profile(
        project_id,
        profile_id=profile_id,
        reason=reason,
        workflow_task_id=workflow_task_id,
    )
