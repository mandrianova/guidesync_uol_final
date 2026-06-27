from __future__ import annotations

from guidesync_agent.schemas import (
    ProjectPipelineState,
    ProjectRunRequest,
    ProjectWorkflowPlan,
    ProjectWorkflowTask,
)
from guidesync_agent.services.workflow_planner import ProjectWorkflowPlanner


def list_project_workflow_tasks(project_id: str) -> list[ProjectWorkflowTask] | None:
    return ProjectWorkflowPlanner().list_project_workflow_tasks(project_id)


def project_pipeline_state(project_id: str) -> ProjectPipelineState | None:
    return ProjectWorkflowPlanner().latest_project_pipeline_state(project_id)


def enqueue_profile_rebuild(project_id: str) -> ProjectWorkflowPlan | None:
    return ProjectWorkflowPlanner().enqueue_profile_rebuild(
        project_id,
        reason="manual_profile_rebuild",
    )


def enqueue_initial_knowledge_base(project_id: str) -> ProjectWorkflowPlan | None:
    return ProjectWorkflowPlanner().enqueue_initial_knowledge_base(
        project_id,
        reason="manual_knowledge_index",
    )


def enqueue_change_analysis_pipeline(
    project_id: str,
    request: ProjectRunRequest,
) -> ProjectWorkflowPlan | None:
    return ProjectWorkflowPlanner().enqueue_change_analysis_pipeline(project_id, request)
