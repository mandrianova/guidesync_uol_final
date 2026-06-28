from __future__ import annotations

from datetime import UTC, datetime

from guidesync_agent.controllers.knowledge import create_project_index_run
from guidesync_agent.controllers.repositories import sync_repository_now
from guidesync_agent.pipeline import run_guidesync, save_run_state
from guidesync_agent.schemas import (
    ChangeAnalysisWorkflowInput,
    ChangeAnalysisWorkflowResult,
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
    ValidationFinding,
)
from guidesync_agent.storage import create_project_workflow_store, create_run_store
from guidesync_agent.workflows.project_profile import rebuild_project_profile


class ProjectWorkflowExecutor:
    def claim_next_task(self) -> ProjectWorkflowTask | None:
        return create_project_workflow_store().claim_next()

    async def execute(self, task: ProjectWorkflowTask) -> ProjectWorkflowTask:
        try:
            completed = await self.execute_by_kind(task)
            return create_project_workflow_store().save(
                completed.model_copy(
                    update={
                        "status": ProjectWorkflowTaskStatus.COMPLETED,
                        "completed_at": datetime.now(UTC),
                    }
                )
            )
        except Exception as exc:  # noqa: BLE001 - persist workflow failures for UI
            return create_project_workflow_store().save(
                task.model_copy(
                    update={
                        "status": ProjectWorkflowTaskStatus.FAILED,
                        "completed_at": datetime.now(UTC),
                        "error_message": str(exc),
                        "warnings": [*task.warnings, str(exc)],
                    }
                )
            )

    async def execute_by_kind(self, task: ProjectWorkflowTask) -> ProjectWorkflowTask:
        if task.kind == ProjectWorkflowTaskKind.REPOSITORY_SYNC:
            return execute_repository_sync(task)
        if task.kind == ProjectWorkflowTaskKind.PROJECT_PROFILE:
            return execute_project_profile(task)
        if task.kind == ProjectWorkflowTaskKind.KNOWLEDGE_INDEX:
            return execute_knowledge_index(task)
        if task.kind == ProjectWorkflowTaskKind.CHANGE_ANALYSIS:
            return await execute_change_analysis(task)
        if task.kind == ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH:
            return execute_post_analysis_refresh(task)
        raise ValueError(f"Unsupported workflow task kind: {task.kind}")


def execute_repository_sync(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    task_input = RepositorySyncWorkflowInput.model_validate(task.input)
    repository_tasks = []
    for repository_id in task_input.repository_ids:
        sync_repository_now(task.project_id, repository_id)
        repository_tasks.append(
            RepositorySyncTask(project_id=task.project_id, repository_id=repository_id)
        )
    return task.model_copy(
        update={
            "result": RepositorySyncWorkflowResult(repository_tasks=repository_tasks),
        }
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
        update={
            "result": ProjectProfileWorkflowResult(
                profile_snapshot_id=profile.id
            )
        }
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


async def execute_change_analysis(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    task_input = ChangeAnalysisWorkflowInput.model_validate(task.input)
    run = create_run_store().get(task_input.run_id)
    if run is None:
        raise ValueError(f"Workflow run not found: {task_input.run_id}")
    running = run.model_copy(update={"status": "running"})
    create_run_store().save(running)
    try:
        result = await run_guidesync(run.request, workflow_task_id=task.id)
    except Exception as exc:  # noqa: BLE001 - save run failure and task failure
        save_run_state(
            run.request,
            "failed",
            [ValidationFinding(severity="error", check="workflow", message=str(exc))],
        )
        raise
    return task.model_copy(
        update={"result": ChangeAnalysisWorkflowResult(report_run_id=result.run_id)}
    )


def execute_post_analysis_refresh(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    run = create_project_index_run(task.project_id, ProjectKnowledgeIndexRequest())
    return task.model_copy(
        update={
            "result": PostAnalysisKnowledgeRefreshResult(
                knowledge_index_run_id=run.id,
                annotation_run_ids=[],
            )
        }
    )
