from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from storage_test_utils import sqlite_database_url

from guidesync_agent.schemas import (
    ChangeAnalysisUnitWorkflowInput,
    ChangeAnalysisWorkUnit,
    ChangedFileRef,
    ChangeSynthesisWorkflowInput,
    KnowledgeIndexWorkflowInput,
    PostAnalysisKnowledgeRefreshInput,
    ProjectCreate,
    ProjectProfileSnapshot,
    ProjectProfileStatus,
    ProjectProfileWorkflowInput,
    ProjectRepository,
    ProjectRunRequest,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProjectWorkflowTaskStatus,
    RetiredChangeAnalysisWorkflowInput,
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
        ),
    )

    assert plan is not None
    assert plan.run is not None
    assert plan.run.status == "blocked"
    assert [task.kind for task in plan.tasks] == [
        ProjectWorkflowTaskKind.REPOSITORY_SYNC,
        ProjectWorkflowTaskKind.PROJECT_PROFILE,
        ProjectWorkflowTaskKind.KNOWLEDGE_INDEX,
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS_PLAN,
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


def test_failed_analysis_unit_cancels_synthesis_and_refresh(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = sqlite_database_url(tmp_path / "workflow-unit-failure.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    store = DatabaseProjectWorkflowStore(database_url)
    unit_tasks = [
        store.enqueue(analysis_unit_task("project-units", index)) for index in range(5)
    ]
    for unit_task in unit_tasks[:4]:
        store.save(unit_task.model_copy(update={"status": ProjectWorkflowTaskStatus.COMPLETED}))
    store.save(
        unit_tasks[4].model_copy(
            update={
                "status": ProjectWorkflowTaskStatus.FAILED,
                "error_message": "model deadline exceeded",
            }
        )
    )
    synthesis = store.enqueue(
        ProjectWorkflowTask(
            project_id="project-units",
            kind=ProjectWorkflowTaskKind.CHANGE_SYNTHESIS,
            depends_on_task_ids=[item.id for item in unit_tasks],
            input=ChangeSynthesisWorkflowInput(
                run_id="run-units",
                plan_task_id="plan-units",
                unit_task_ids=[item.id for item in unit_tasks],
            ),
        )
    )
    refresh = store.enqueue(
        ProjectWorkflowTask(
            project_id="project-units",
            kind=ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH,
            depends_on_task_ids=[synthesis.id],
            input=PostAnalysisKnowledgeRefreshInput(run_id="run-units"),
        )
    )

    assert store.claim_next() is None

    tasks = {task.id: task for task in store.list_tasks("project-units")}
    assert all(
        tasks[item.id].status is ProjectWorkflowTaskStatus.COMPLETED
        for item in unit_tasks[:4]
    )
    assert tasks[synthesis.id].status is ProjectWorkflowTaskStatus.CANCELLED
    assert tasks[refresh.id].status is ProjectWorkflowTaskStatus.CANCELLED


def test_expired_analysis_unit_is_retried_then_failed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = sqlite_database_url(tmp_path / "workflow-unit-lease.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    store = DatabaseProjectWorkflowStore(database_url)
    store.enqueue(analysis_unit_task("project-lease", 1))
    first_claim = store.claim_next()
    assert first_claim is not None
    expired = first_claim.model_copy(
        update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    store.save(expired)

    second_claim = store.claim_next()

    assert second_claim is not None
    assert second_claim.attempt_count == 2
    store.save(
        second_claim.model_copy(
            update={"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
    )

    assert store.claim_next() is None
    terminal = store.get(second_claim.id)
    assert terminal is not None
    assert terminal.status is ProjectWorkflowTaskStatus.FAILED
    assert terminal.error_message == "Workflow task lease expired."


def test_retired_analysis_task_is_readable_and_terminalized(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = sqlite_database_url(tmp_path / "workflow-retired-analysis.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    store = DatabaseProjectWorkflowStore(database_url)
    old_task = store.enqueue(
        ProjectWorkflowTask(
            project_id="project-retired",
            kind=ProjectWorkflowTaskKind.RETIRED_CHANGE_ANALYSIS,
            input=RetiredChangeAnalysisWorkflowInput(run_id="run-retired"),
        )
    )
    store.save(
        old_task.model_copy(
            update={"status": ProjectWorkflowTaskStatus.RUNNING}
        )
    )

    claimed = store.claim_next()
    assert claimed is not None
    saved = asyncio.run(ProjectWorkflowExecutor().execute(claimed))

    assert saved.status is ProjectWorkflowTaskStatus.FAILED
    assert saved.error_message == "Unsupported workflow task kind: change_analysis"


def analysis_unit_task(project_id: str, index: int) -> ProjectWorkflowTask:
    path = f"src/module_{index}.py"
    unit = ChangeAnalysisWorkUnit(
        id=f"analysis-unit-{index}",
        repository_id="repo-units",
        files=[ChangedFileRef(path=path, status="M")],
        grouping_reason="test fixture",
    )
    return ProjectWorkflowTask(
        project_id=project_id,
        kind=ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT,
        input=ChangeAnalysisUnitWorkflowInput(run_id="run-units", work_unit=unit),
    )
