from __future__ import annotations

from guidesync_agent.schemas import (
    ChangeAnalysisPlanWorkflowInput,
    ChangeAnalysisWorkflowInput,
    ChangeSynthesisWorkflowInput,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    KnowledgeIndexStatus,
    KnowledgeIndexWorkflowInput,
    ProjectConfig,
    ProjectPipelineState,
    ProjectProfileBuildReason,
    ProjectProfileStatus,
    ProjectProfileWorkflowInput,
    ProjectRepository,
    ProjectRunRequest,
    ProjectWorkflowPlan,
    ProjectWorkflowRequestedBy,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProjectWorkflowTaskStatus,
    RepositoryCacheStatus,
    RepositorySyncWorkflowInput,
    RunSummary,
    ScreenshotCaptureWorkflowInput,
)
from guidesync_agent.services.reports.runs import (
    build_project_run_request,
    build_retry_run_request,
    project_id_for_run,
    workflow_planning_run_result,
)
from guidesync_agent.storage import (
    create_knowledge_store,
    create_project_profile_store,
    create_project_store,
    create_project_workflow_store,
    create_run_store,
)


class ProjectWorkflowPlanner:
    def enqueue_profile_rebuild(
        self,
        project_id: str,
        *,
        reason: ProjectProfileBuildReason,
        repository_ids: set[str] | None = None,
    ) -> ProjectWorkflowPlan | None:
        project = create_project_store().get(project_id)
        if project is None:
            return None
        tasks = self.enqueue_missing_repository_sync(
            project,
            reason,
            repository_ids=repository_ids,
        )
        profile_task = self.enqueue_task(
            ProjectWorkflowTask(
                project_id=project.id,
                kind=ProjectWorkflowTaskKind.PROJECT_PROFILE,
                depends_on_task_ids=[task.id for task in tasks],
                dedupe_key="project_profile",
                requested_by=ProjectWorkflowRequestedBy.API,
                reason=reason,
                input=ProjectProfileWorkflowInput(),
            )
        )
        return ProjectWorkflowPlan(project_id=project.id, tasks=[*tasks, profile_task])

    def enqueue_initial_knowledge_base(
        self,
        project_id: str,
        *,
        reason: str,
    ) -> ProjectWorkflowPlan | None:
        project = create_project_store().get(project_id)
        if project is None:
            return None
        tasks = self.ensure_profile_and_kb_tasks(project, reason)
        return ProjectWorkflowPlan(project_id=project.id, tasks=tasks)

    def enqueue_change_analysis_pipeline(
        self,
        project_id: str,
        request: ProjectRunRequest,
    ) -> ProjectWorkflowPlan | None:
        project = create_project_store().get(project_id)
        if project is None:
            return None
        run_request = build_project_run_request(project=project, request=request)
        return self.enqueue_run_request(project, run_request, reason="run_analysis")

    def retry_change_analysis_run(self, run_id: str) -> ProjectWorkflowPlan:
        previous = create_run_store().get(run_id)
        if previous is None:
            raise KeyError(f"Run not found: {run_id}")
        if previous.status not in {"failed", "partial_failure", "cancelled"}:
            raise ValueError(f"Run is not retryable: {run_id} ({previous.status})")
        project_id = project_id_for_run(previous.request)
        project = create_project_store().get(project_id)
        if project is None:
            raise ValueError(f"Project not found for run: {run_id}")
        return self.enqueue_run_request(
            project,
            build_retry_run_request(previous),
            reason="retry_report_run",
        )

    def retry_change_synthesis(self, run_id: str) -> ProjectWorkflowPlan:
        run = require_retry_run(run_id)
        if run.status != "failed" or run.update is not None:
            raise ValueError("Final-stage retry requires a failed run without a report draft.")
        project_id = project_id_for_run(run.request)
        tasks = create_project_workflow_store().list_tasks(project_id)
        ensure_no_active_run_stage(tasks, run_id)
        analysis_task = latest_completed_run_task(
            tasks,
            run_id,
            ProjectWorkflowTaskKind.CHANGE_ANALYSIS,
        )
        analysis_input = ChangeAnalysisWorkflowInput.model_validate(analysis_task.input)
        synthesis = self.enqueue_task(
            ProjectWorkflowTask(
                project_id=project_id,
                kind=ProjectWorkflowTaskKind.CHANGE_SYNTHESIS,
                depends_on_task_ids=[analysis_task.id],
                dedupe_key=f"change_synthesis:{run_id}",
                requested_by=ProjectWorkflowRequestedBy.API,
                reason="retry_report_final_stage",
                input=ChangeSynthesisWorkflowInput(
                    run_id=run_id,
                    plan_task_id=analysis_input.plan_task_id,
                    analysis_task_id=analysis_task.id,
                ),
            )
        )
        store = create_run_store()
        store.save(run.model_copy(update={"status": "planning"}))
        store.record_run_event(
            run_id,
            "planning",
            "Final report synthesis retry queued from completed change analysis.",
            "synthesis",
        )
        return ProjectWorkflowPlan(
            project_id=project_id,
            tasks=[synthesis],
            run=run_summary_for_id(project_id, run_id),
        )

    def retry_screenshot_capture(self, run_id: str) -> ProjectWorkflowPlan:
        run = require_retry_run(run_id)
        if run.status != "completed" or run.update is None:
            raise ValueError("Screenshot retry requires a completed release report.")
        if not (run.request.task_interface_url or "").strip():
            raise ValueError("Screenshot retry requires a task interface URL.")
        if not run.update.screenshot_requests:
            raise ValueError("The release report has no planned screenshot requests.")
        project_id = project_id_for_run(run.request)
        tasks = create_project_workflow_store().list_tasks(project_id)
        ensure_no_active_run_stage(
            tasks,
            run_id,
            kinds={ProjectWorkflowTaskKind.SCREENSHOT_CAPTURE},
        )
        synthesis = latest_completed_run_task(
            tasks,
            run_id,
            ProjectWorkflowTaskKind.CHANGE_SYNTHESIS,
        )
        screenshot = self.enqueue_task(
            ProjectWorkflowTask(
                project_id=project_id,
                kind=ProjectWorkflowTaskKind.SCREENSHOT_CAPTURE,
                depends_on_task_ids=[synthesis.id],
                dedupe_key=f"screenshot_capture:{run_id}",
                requested_by=ProjectWorkflowRequestedBy.API,
                reason="retry_optional_screenshots",
                input=ScreenshotCaptureWorkflowInput(
                    run_id=run_id,
                    synthesis_task_id=synthesis.id,
                    regenerate=True,
                ),
            )
        )
        return ProjectWorkflowPlan(
            project_id=project_id,
            tasks=[screenshot],
            run=run_summary_for_id(project_id, run_id),
        )

    def enqueue_run_request(
        self,
        project: ProjectConfig,
        run_request: GuideSyncRunRequest,
        *,
        reason: str,
    ) -> ProjectWorkflowPlan:
        create_run_store().save(workflow_planning_run_result(run_request))
        run = next(
            summary
            for summary in create_run_store().list_runs(project_id=project.id)
            if summary.run_id == run_request.run_id
        )
        tasks = self.ensure_profile_and_kb_tasks(project, f"{reason}_prerequisite")
        analysis_plan_task = self.enqueue_task(
            ProjectWorkflowTask(
                project_id=project.id,
                kind=ProjectWorkflowTaskKind.CHANGE_ANALYSIS_PLAN,
                depends_on_task_ids=[task.id for task in tasks] if tasks else [],
                dedupe_key=f"change_analysis_plan:{run.run_id}",
                requested_by=ProjectWorkflowRequestedBy.API,
                reason=reason,
                input=ChangeAnalysisPlanWorkflowInput(run_id=run.run_id),
            )
        )
        return ProjectWorkflowPlan(
            project_id=project.id,
            tasks=[*tasks, analysis_plan_task],
            run=run,
        )

    def list_project_workflow_tasks(self, project_id: str) -> list[ProjectWorkflowTask] | None:
        if create_project_store().get(project_id) is None:
            return None
        return create_project_workflow_store().list_tasks(project_id)

    def latest_project_pipeline_state(self, project_id: str) -> ProjectPipelineState | None:
        project = create_project_store().get(project_id)
        if project is None:
            return None
        profile_ready = latest_profile_ready(project.id)
        kb_ready = latest_knowledge_base_ready(project.id)
        blocked_reason = None
        if not profile_ready:
            blocked_reason = "Project profile has not completed yet."
        elif not kb_ready:
            blocked_reason = "Initial knowledge base has not completed yet."
        return ProjectPipelineState(
            project_id=project.id,
            profile_ready=profile_ready,
            knowledge_base_ready=kb_ready,
            blocked_reason=blocked_reason,
            tasks=create_project_workflow_store().list_tasks(project.id),
        )

    def ensure_profile_and_kb_tasks(
        self,
        project: ProjectConfig,
        reason: str,
    ) -> list[ProjectWorkflowTask]:
        tasks = self.enqueue_missing_repository_sync(project, reason)
        if not latest_profile_ready(project.id):
            profile_task = self.enqueue_task(
                ProjectWorkflowTask(
                    project_id=project.id,
                    kind=ProjectWorkflowTaskKind.PROJECT_PROFILE,
                    depends_on_task_ids=[task.id for task in tasks],
                    dedupe_key="project_profile",
                    requested_by=ProjectWorkflowRequestedBy.SYSTEM,
                    reason=reason,
                    input=ProjectProfileWorkflowInput(),
                )
            )
            tasks.append(profile_task)
        if not latest_knowledge_base_ready(project.id):
            kb_task = self.enqueue_task(
                ProjectWorkflowTask(
                    project_id=project.id,
                    kind=ProjectWorkflowTaskKind.KNOWLEDGE_INDEX,
                    depends_on_task_ids=[tasks[-1].id] if tasks else [],
                    dedupe_key="initial_knowledge_index",
                    requested_by=ProjectWorkflowRequestedBy.SYSTEM,
                    reason=reason,
                    input=KnowledgeIndexWorkflowInput(),
                )
            )
            tasks.append(kb_task)
        return tasks

    def enqueue_missing_repository_sync(
        self,
        project: ProjectConfig,
        reason: str,
        *,
        repository_ids: set[str] | None = None,
    ) -> list[ProjectWorkflowTask]:
        pending_repository_ids = [
            repository.id
            for repository in project.repositories
            if repository.url.strip()
            and repository_needs_sync(repository, repository_ids)
        ]
        if not pending_repository_ids:
            return []
        task = ProjectWorkflowTask(
            project_id=project.id,
            kind=ProjectWorkflowTaskKind.REPOSITORY_SYNC,
            dedupe_key=f"repository_sync:{','.join(sorted(pending_repository_ids))}",
            requested_by=ProjectWorkflowRequestedBy.SYSTEM,
            reason=reason,
            input=RepositorySyncWorkflowInput(repository_ids=pending_repository_ids),
        )
        return [self.enqueue_task(task)]

    @staticmethod
    def enqueue_task(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
        return create_project_workflow_store().enqueue(task)


def latest_profile_ready(project_id: str) -> bool:
    profile = create_project_profile_store().latest(project_id)
    return profile is not None and profile.status == ProjectProfileStatus.COMPLETED


def latest_knowledge_base_ready(project_id: str) -> bool:
    return any(
        run.status == KnowledgeIndexStatus.COMPLETED
        for run in create_knowledge_store().list_index_runs(project_id=project_id)
    )


def repository_needs_sync(
    repository: ProjectRepository,
    repository_ids: set[str] | None,
) -> bool:
    if repository_ids is not None:
        return repository.id in repository_ids
    return repository.cache_status is not RepositoryCacheStatus.READY


def require_retry_run(run_id: str) -> GuideSyncRunResult:
    run = create_run_store().get(run_id)
    if run is None:
        raise KeyError(f"Run not found: {run_id}")
    return run


def latest_completed_run_task(
    tasks: list[ProjectWorkflowTask],
    run_id: str,
    kind: ProjectWorkflowTaskKind,
) -> ProjectWorkflowTask:
    matches = [
        task
        for task in tasks
        if task.kind is kind
        and task.status is ProjectWorkflowTaskStatus.COMPLETED
        and getattr(task.input, "run_id", None) == run_id
    ]
    if not matches:
        raise ValueError(f"No completed {kind.value} task exists for run {run_id}.")
    return max(matches, key=lambda task: task.sequence)


def ensure_no_active_run_stage(
    tasks: list[ProjectWorkflowTask],
    run_id: str,
    *,
    kinds: set[ProjectWorkflowTaskKind] | None = None,
) -> None:
    active_statuses = {
        ProjectWorkflowTaskStatus.QUEUED,
        ProjectWorkflowTaskStatus.RUNNING,
        ProjectWorkflowTaskStatus.RETRYING,
        ProjectWorkflowTaskStatus.BLOCKED,
    }
    active = next(
        (
            task
            for task in tasks
            if (kinds is None or task.kind in kinds)
            and task.status in active_statuses
            and getattr(task.input, "run_id", None) == run_id
        ),
        None,
    )
    if active is not None:
        raise ValueError(f"Workflow stage is already active for run {run_id}: {active.id}")


def run_summary_for_id(project_id: str, run_id: str) -> RunSummary:
    return next(
        summary
        for summary in create_run_store().list_runs(project_id=project_id)
        if summary.run_id == run_id
    )
