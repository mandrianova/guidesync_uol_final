from __future__ import annotations

from guidesync_agent.schemas import (
    ProjectPipelineState,
    ProjectProfileBuildReason,
    ProjectRunRequest,
    ProjectWorkflowPlan,
    ProjectWorkflowTask,
)
from guidesync_agent.services.workflow_planner import ProjectWorkflowPlanner
from guidesync_agent.storage import create_project_workflow_store


def list_project_workflow_tasks(project_id: str) -> list[ProjectWorkflowTask] | None:
    return ProjectWorkflowPlanner().list_project_workflow_tasks(project_id)


def project_pipeline_state(project_id: str) -> ProjectPipelineState | None:
    return ProjectWorkflowPlanner().latest_project_pipeline_state(project_id)


def cancel_project_workflow_task(project_id: str, task_id: str) -> ProjectWorkflowTask:
    return create_project_workflow_store().cancel_task(
        project_id,
        task_id,
        reason="Cancelled by user.",
    )


def enqueue_profile_rebuild(project_id: str) -> ProjectWorkflowPlan | None:
    return ProjectWorkflowPlanner().enqueue_profile_rebuild(
        project_id,
        reason=ProjectProfileBuildReason.MANUAL_REBUILD,
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
