from __future__ import annotations

from datetime import UTC, datetime

from guidesync_agent.controllers.knowledge import create_project_index_run
from guidesync_agent.controllers.repositories import sync_repository_now
from guidesync_agent.schemas import (
    KnowledgeIndexWorkflowInput,
    KnowledgeIndexWorkflowResult,
    PostAnalysisKnowledgeRefreshResult,
    ProjectKnowledgeIndexRequest,
    ProjectProfileStatus,
    ProjectProfileWorkflowInput,
    ProjectProfileWorkflowResult,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProjectWorkflowTaskStatus,
    RepositorySyncTask,
    RepositorySyncWorkflowInput,
    RepositorySyncWorkflowResult,
)
from guidesync_agent.storage import create_project_workflow_store
from guidesync_agent.workflows.project_profile import rebuild_project_profile

from .workflow_change_analysis import (
    execute_change_analysis_plan,
    execute_change_analysis_unit,
    execute_change_synthesis,
    fail_analysis_run,
)


class ProjectWorkflowExecutor:
    def claim_next_task(self) -> ProjectWorkflowTask | None:
        return create_project_workflow_store().claim_next()

    async def execute(self, task: ProjectWorkflowTask) -> ProjectWorkflowTask:
        try:
            completed = await self.execute_by_kind(task)
            return save_completed_task(completed)
        except Exception as exc:  # noqa: BLE001 - workflow boundary persists terminal errors
            return save_failed_or_retryable_task(task, exc)

    async def execute_by_kind(self, task: ProjectWorkflowTask) -> ProjectWorkflowTask:
        handlers = {
            ProjectWorkflowTaskKind.REPOSITORY_SYNC: execute_repository_sync,
            ProjectWorkflowTaskKind.PROJECT_PROFILE: execute_project_profile,
            ProjectWorkflowTaskKind.KNOWLEDGE_INDEX: execute_knowledge_index,
            ProjectWorkflowTaskKind.CHANGE_ANALYSIS_PLAN: execute_change_analysis_plan,
            ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT: execute_change_analysis_unit,
            ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH: (
                execute_post_analysis_refresh
            ),
        }
        if task.kind is ProjectWorkflowTaskKind.CHANGE_SYNTHESIS:
            return await execute_change_synthesis(task)
        handler = handlers.get(task.kind)
        if handler is None:
            raise ValueError(f"Unsupported workflow task kind: {task.kind}")
        return handler(task)


def save_completed_task(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    completed = task.model_copy(
        update={
            "status": ProjectWorkflowTaskStatus.COMPLETED,
            "completed_at": datetime.now(UTC),
            "lease_token": None,
            "lease_expires_at": None,
        }
    )
    return create_project_workflow_store().save(completed)


def save_failed_or_retryable_task(
    task: ProjectWorkflowTask,
    error: Exception,
) -> ProjectWorkflowTask:
    retryable = (
        task.kind is ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT
        and task.attempt_count < task.max_attempts
    )
    status = ProjectWorkflowTaskStatus.QUEUED if retryable else ProjectWorkflowTaskStatus.FAILED
    message = str(error)
    failed = task.model_copy(
        update={
            "status": status,
            "completed_at": None if retryable else datetime.now(UTC),
            "error_message": message,
            "warnings": [*task.warnings, message],
            "lease_token": None,
            "lease_expires_at": None,
        }
    )
    if not retryable:
        fail_analysis_run(task, message)
    return create_project_workflow_store().save(failed)


def execute_repository_sync(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    task_input = RepositorySyncWorkflowInput.model_validate(task.input)
    repository_tasks = []
    for repository_id in task_input.repository_ids:
        sync_repository_now(task.project_id, repository_id)
        repository_tasks.append(
            RepositorySyncTask(project_id=task.project_id, repository_id=repository_id)
        )
    return task.model_copy(
        update={"result": RepositorySyncWorkflowResult(repository_tasks=repository_tasks)}
    )


def execute_project_profile(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    task_input = ProjectProfileWorkflowInput.model_validate(task.input)
    profile = rebuild_project_profile(
        task.project_id,
        profile_id=task_input.profile_id,
        reason=task.reason or "workflow",
        workflow_task_id=task.id,
    )
    if profile is None:
        raise ValueError(f"Project profile build did not produce a profile: {task.project_id}")
    if profile.status == ProjectProfileStatus.FAILED:
        raise RuntimeError(profile.error_message or "Project profile build failed.")
    return task.model_copy(
        update={"result": ProjectProfileWorkflowResult(profile_snapshot_id=profile.id)}
    )


def execute_knowledge_index(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    task_input = KnowledgeIndexWorkflowInput.model_validate(task.input)
    run = create_project_index_run(
        task.project_id,
        ProjectKnowledgeIndexRequest(max_file_bytes=task_input.max_file_bytes),
    )
    return task.model_copy(
        update={"result": KnowledgeIndexWorkflowResult(knowledge_index_run_id=run.id)}
    )


def execute_post_analysis_refresh(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    run = create_project_index_run(task.project_id, ProjectKnowledgeIndexRequest())
    result = PostAnalysisKnowledgeRefreshResult(
        knowledge_index_run_id=run.id,
        annotation_run_ids=[],
    )
    return task.model_copy(update={"result": result})
