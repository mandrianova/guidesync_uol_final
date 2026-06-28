from __future__ import annotations

import asyncio
from pathlib import Path

from storage_test_utils import sqlite_database_url

from guidesync_agent.schemas import (
    KnowledgeIndexWorkflowInput,
    ProjectCreate,
    ProjectProfileSnapshot,
    ProjectProfileStatus,
    ProjectProfileWorkflowInput,
    ProjectRepository,
    ProjectRunRequest,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProjectWorkflowTaskStatus,
    ProviderConfig,
    ProviderKind,
)
from guidesync_agent.services import workflow_executor as workflow_executor_module
from guidesync_agent.services.workflow_executor import ProjectWorkflowExecutor
from guidesync_agent.services.workflow_planner import ProjectWorkflowPlanner
from guidesync_agent.storage import (
    DatabaseProjectStore,
    DatabaseProjectWorkflowStore,
    create_project_workflow_store,
)


def test_workflow_store_claims_fifo_inside_project(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "workflow.db"))
    store = create_project_workflow_store()
    first = store.enqueue(
        ProjectWorkflowTask(
            project_id="project-1",
            kind=ProjectWorkflowTaskKind.KNOWLEDGE_INDEX,
            input=KnowledgeIndexWorkflowInput(),
        )
    )
    second = store.enqueue(
        ProjectWorkflowTask(
            project_id="project-1",
            kind=ProjectWorkflowTaskKind.KNOWLEDGE_INDEX,
            input=KnowledgeIndexWorkflowInput(),
        )
    )

    claimed = store.claim_next()
    blocked = store.claim_next()

    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status == ProjectWorkflowTaskStatus.RUNNING
    assert blocked is None
    store.save(claimed.model_copy(update={"status": ProjectWorkflowTaskStatus.COMPLETED}))
    next_claimed = store.claim_next()
    assert next_claimed is not None
    assert next_claimed.id == second.id


def test_planner_enqueues_analysis_after_profile_and_kb(monkeypatch, tmp_path: Path) -> None:
    database_url = sqlite_database_url(tmp_path / "planner.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    project = DatabaseProjectStore(database_url).save(
        ProjectCreate(
            name="Planner project",
            repositories=[
                ProjectRepository(
                    id="repo-planner",
                    name="fixture",
                    url="https://github.com/example/repo",
                    default_branch="main",
                )
            ],
        )
    )

    plan = ProjectWorkflowPlanner().enqueue_change_analysis_pipeline(
        project.id,
        ProjectRunRequest(
            goal="Write release notes.",
            provider=ProviderConfig(provider=ProviderKind.MOCK, model="mock:deterministic"),
        ),
    )

    assert plan is not None
    assert plan.run is not None
    assert plan.run.status == "blocked"
    assert [task.kind for task in plan.tasks] == [
        ProjectWorkflowTaskKind.REPOSITORY_SYNC,
        ProjectWorkflowTaskKind.PROJECT_PROFILE,
        ProjectWorkflowTaskKind.KNOWLEDGE_INDEX,
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS,
        ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH,
    ]
    assert plan.tasks[3].depends_on_task_ids == [
        plan.tasks[0].id,
        plan.tasks[1].id,
        plan.tasks[2].id,
    ]


def test_workflow_executor_marks_failed_project_profile_task_failed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = sqlite_database_url(tmp_path / "workflow-profile-failure.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    store = DatabaseProjectWorkflowStore(database_url)
    task = store.enqueue(
        ProjectWorkflowTask(
            project_id="project-profile-failure",
            kind=ProjectWorkflowTaskKind.PROJECT_PROFILE,
            input=ProjectProfileWorkflowInput(),
        )
    )
    claimed = store.claim_next()

    def failed_profile(
        project_id: str,
        *,
        profile_id: str | None = None,
        reason: str = "manual",
        workflow_task_id: str | None = None,
    ) -> ProjectProfileSnapshot:
        return ProjectProfileSnapshot(
            id=profile_id or "profile-failed",
            project_id=project_id,
            status=ProjectProfileStatus.FAILED,
            prompt_version="test-profile",
            error_message="profile timeout",
        )

    monkeypatch.setattr(workflow_executor_module, "rebuild_project_profile", failed_profile)

    assert claimed is not None
    saved = asyncio.run(ProjectWorkflowExecutor().execute(claimed))

    assert saved.id == task.id
    assert saved.status == ProjectWorkflowTaskStatus.FAILED
    assert saved.error_message == "profile timeout"
