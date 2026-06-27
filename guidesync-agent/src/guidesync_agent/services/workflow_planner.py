from __future__ import annotations

from guidesync_agent.schemas import (
    ChangeAnalysisWorkflowInput,
    KnowledgeIndexStatus,
    KnowledgeIndexWorkflowInput,
    PostAnalysisKnowledgeRefreshInput,
    ProjectConfig,
    ProjectPipelineState,
    ProjectProfileStatus,
    ProjectProfileWorkflowInput,
    ProjectRunRequest,
    ProjectWorkflowPlan,
    ProjectWorkflowRequestedBy,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    RepositorySyncWorkflowInput,
)
from guidesync_agent.services import ReportRunService
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
        reason: str,
    ) -> ProjectWorkflowPlan | None:
        project = create_project_store().get(project_id)
        if project is None:
            return None
        tasks = self.enqueue_missing_repository_sync(project, reason)
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
        run_service = ReportRunService(create_run_store())
        run_request = run_service.build_project_run_request(project=project, request=request)
        create_run_store().save(run_service.blocked_run_result(run_request))
        run = next(
            summary
            for summary in create_run_store().list_runs(project_id=project.id)
            if summary.run_id == run_request.run_id
        )
        tasks = self.ensure_profile_and_kb_tasks(project, "run_analysis_prerequisite")
        analysis_task = self.enqueue_task(
            ProjectWorkflowTask(
                project_id=project.id,
                kind=ProjectWorkflowTaskKind.CHANGE_ANALYSIS,
                depends_on_task_ids=[task.id for task in tasks] if tasks else [],
                dedupe_key=f"change_analysis:{run.run_id}",
                requested_by=ProjectWorkflowRequestedBy.API,
                reason="run_analysis",
                input=ChangeAnalysisWorkflowInput(run_id=run.run_id),
            )
        )
        refresh_task = self.enqueue_task(
            ProjectWorkflowTask(
                project_id=project.id,
                kind=ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH,
                depends_on_task_ids=[analysis_task.id],
                dedupe_key=f"post_analysis_knowledge_refresh:{run.run_id}",
                requested_by=ProjectWorkflowRequestedBy.SYSTEM,
                reason="post_analysis_refresh",
                input=PostAnalysisKnowledgeRefreshInput(run_id=run.run_id),
            )
        )
        return ProjectWorkflowPlan(
            project_id=project.id,
            tasks=[*tasks, analysis_task, refresh_task],
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
    ) -> list[ProjectWorkflowTask]:
        repository_ids = [
            repository.id
            for repository in project.repositories
            if repository.url.strip() and repository.cache_status.value != "ready"
        ]
        if not repository_ids:
            return []
        task = ProjectWorkflowTask(
            project_id=project.id,
            kind=ProjectWorkflowTaskKind.REPOSITORY_SYNC,
            dedupe_key=f"repository_sync:{','.join(sorted(repository_ids))}",
            requested_by=ProjectWorkflowRequestedBy.SYSTEM,
            reason=reason,
            input=RepositorySyncWorkflowInput(repository_ids=repository_ids),
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
