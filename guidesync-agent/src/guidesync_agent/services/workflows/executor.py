from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime

from guidesync_agent.controllers.knowledge import create_project_index_run
from guidesync_agent.controllers.repositories import sync_repository_now
from guidesync_agent.schemas import (
    ChangeAnalysisUnitWorkflowInput,
    KnowledgeIndexWorkflowInput,
    KnowledgeIndexWorkflowResult,
    PostAnalysisKnowledgeRefreshResult,
    ProjectKnowledgeIndexRequest,
    ProjectProfileStatus,
    ProjectProfileWorkflowInput,
    ProjectProfileWorkflowResult,
    ProjectWorkflowProgress,
    ProjectWorkflowStage,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProjectWorkflowTaskStatus,
    RepositorySyncTask,
    RepositorySyncWorkflowInput,
    RepositorySyncWorkflowResult,
)
from guidesync_agent.services.ui_evidence.workflow import (
    execute_screenshot_capture,
    fail_screenshot_capture,
)
from guidesync_agent.services.video.presentation import (
    execute_video_presentation,
    fail_video_presentation,
)
from guidesync_agent.storage import create_project_workflow_store
from guidesync_agent.workflows.project_profile import rebuild_project_profile

from .change_analysis import (
    execute_change_analysis,
    execute_change_analysis_plan,
    execute_change_analysis_unit,
    execute_change_synthesis,
    fail_analysis_run,
)


class ProjectWorkflowExecutor:
    def claim_next_task(self) -> ProjectWorkflowTask | None:
        return create_project_workflow_store().claim_next()

    async def execute(self, task: ProjectWorkflowTask) -> ProjectWorkflowTask:
        heartbeat_task = asyncio.create_task(maintain_task_heartbeat(task))
        try:
            completed = await self.execute_by_kind(task)
            cancelled = cancelled_task(task.id)
            if cancelled is not None:
                return cancelled
            return save_completed_task(completed)
        except Exception as exc:  # noqa: BLE001 - workflow boundary persists terminal errors
            cancelled = cancelled_task(task.id)
            if cancelled is not None:
                return cancelled
            return save_failed_or_retryable_task(task, exc)
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    async def execute_by_kind(self, task: ProjectWorkflowTask) -> ProjectWorkflowTask:
        handlers = {
            ProjectWorkflowTaskKind.REPOSITORY_SYNC: execute_repository_sync,
            ProjectWorkflowTaskKind.PROJECT_PROFILE: execute_project_profile,
            ProjectWorkflowTaskKind.KNOWLEDGE_INDEX: execute_knowledge_index,
            ProjectWorkflowTaskKind.CHANGE_ANALYSIS_PLAN: execute_change_analysis_plan,
            ProjectWorkflowTaskKind.CHANGE_ANALYSIS: execute_change_analysis,
            ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT: execute_change_analysis_unit,
            ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH: (
                execute_post_analysis_refresh
            ),
        }
        if task.kind is ProjectWorkflowTaskKind.CHANGE_SYNTHESIS:
            return await execute_change_synthesis(task)
        if task.kind is ProjectWorkflowTaskKind.SCREENSHOT_CAPTURE:
            return await execute_screenshot_capture(task)
        if task.kind is ProjectWorkflowTaskKind.VIDEO_PRESENTATION:
            return await execute_video_presentation(task)
        handler = handlers.get(task.kind)
        if handler is None:
            raise ValueError(f"Unsupported workflow task kind: {task.kind}")
        return await asyncio.to_thread(handler, task)


async def maintain_task_heartbeat(task: ProjectWorkflowTask) -> None:
    if not task.lease_token:
        return
    store = create_project_workflow_store()
    progress = initial_task_progress(task)
    alive = await asyncio.to_thread(store.heartbeat, task.id, task.lease_token, progress)
    while alive:
        await asyncio.sleep(5)
        alive = await asyncio.to_thread(store.heartbeat, task.id, task.lease_token)


def initial_task_progress(task: ProjectWorkflowTask) -> ProjectWorkflowProgress:
    stage_by_kind = {
        ProjectWorkflowTaskKind.REPOSITORY_SYNC: ProjectWorkflowStage.RUNNING,
        ProjectWorkflowTaskKind.PROJECT_PROFILE: ProjectWorkflowStage.RUNNING,
        ProjectWorkflowTaskKind.KNOWLEDGE_INDEX: ProjectWorkflowStage.REFRESHING_KNOWLEDGE,
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS_PLAN: ProjectWorkflowStage.PLANNING,
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS: ProjectWorkflowStage.ANALYZING,
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT: ProjectWorkflowStage.PREPARING_CONTEXT,
        ProjectWorkflowTaskKind.CHANGE_SYNTHESIS: ProjectWorkflowStage.SYNTHESIZING,
        ProjectWorkflowTaskKind.SCREENSHOT_CAPTURE: (
            ProjectWorkflowStage.CAPTURING_SCREENSHOTS
        ),
        ProjectWorkflowTaskKind.VIDEO_PRESENTATION: (
            ProjectWorkflowStage.GENERATING_PRESENTATION
        ),
        ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH: (
            ProjectWorkflowStage.REFRESHING_KNOWLEDGE
        ),
    }
    total_items = None
    if task.kind is ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT:
        unit_input = ChangeAnalysisUnitWorkflowInput.model_validate(task.input)
        total_items = len(unit_input.work_unit.files)
    return ProjectWorkflowProgress(
        stage=stage_by_kind.get(task.kind, ProjectWorkflowStage.RUNNING),
        message=task_stage_message(task.kind),
        total_items=total_items,
    )


def task_stage_message(kind: ProjectWorkflowTaskKind) -> str:
    messages = {
        ProjectWorkflowTaskKind.REPOSITORY_SYNC: "Synchronizing repositories",
        ProjectWorkflowTaskKind.PROJECT_PROFILE: "Building project profile",
        ProjectWorkflowTaskKind.KNOWLEDGE_INDEX: "Building knowledge index",
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS_PLAN: "Collecting frozen change inventory",
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS: "Building semantic release findings",
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT: "Preparing bounded evidence context",
        ProjectWorkflowTaskKind.CHANGE_SYNTHESIS: "Synthesizing completed analysis artifacts",
        ProjectWorkflowTaskKind.SCREENSHOT_CAPTURE: "Capturing optional UI evidence",
        ProjectWorkflowTaskKind.VIDEO_PRESENTATION: "Generating video presentation",
        ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH: (
            "Refreshing knowledge from completed analysis"
        ),
    }
    return messages.get(kind, "Running workflow task")


def cancelled_task(task_id: str) -> ProjectWorkflowTask | None:
    current = create_project_workflow_store().get(task_id)
    if current is not None and current.status is ProjectWorkflowTaskStatus.CANCELLED:
        return current
    return None


def save_completed_task(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    completed_at = datetime.now(UTC)
    completed = task.model_copy(
        update={
            "status": ProjectWorkflowTaskStatus.COMPLETED,
            "completed_at": completed_at,
            "last_heartbeat_at": completed_at,
            "lease_token": None,
            "lease_expires_at": None,
            "progress": ProjectWorkflowProgress(
                stage=ProjectWorkflowStage.COMPLETED,
                message="Workflow task completed",
                completed_items=task.progress.total_items or task.progress.completed_items,
                total_items=task.progress.total_items,
            ),
        }
    )
    return create_project_workflow_store().save(completed)


def save_failed_or_retryable_task(
    task: ProjectWorkflowTask,
    error: Exception,
) -> ProjectWorkflowTask:
    task = create_project_workflow_store().get(task.id) or task
    finished_at = datetime.now(UTC)
    retryable = (
        task.kind
        in {
            ProjectWorkflowTaskKind.CHANGE_ANALYSIS,
            ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT,
            ProjectWorkflowTaskKind.SCREENSHOT_CAPTURE,
            ProjectWorkflowTaskKind.VIDEO_PRESENTATION,
        }
        and task.attempt_count < task.max_attempts
    )
    status = ProjectWorkflowTaskStatus.RETRYING if retryable else ProjectWorkflowTaskStatus.FAILED
    message = str(error)
    failed = task.model_copy(
        update={
            "status": status,
            "completed_at": None if retryable else finished_at,
            "last_heartbeat_at": finished_at,
            "error_message": message,
            "warnings": [*task.warnings, message],
            "lease_token": None,
            "lease_expires_at": None,
            "progress": ProjectWorkflowProgress(
                stage=(ProjectWorkflowStage.RETRYING if retryable else ProjectWorkflowStage.FAILED),
                message=("Retrying after an error" if retryable else message),
                completed_items=task.progress.completed_items,
                total_items=task.progress.total_items,
            ),
        }
    )
    if not retryable:
        fail_analysis_run(task, message)
    fail_screenshot_capture(failed, retrying=retryable)
    fail_video_presentation(failed, retrying=retryable)
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
        workflow_task_id=task.id,
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
