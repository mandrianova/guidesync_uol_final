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
    LLMConversationStatus,
    LLMConversationTranscript,
    ModelRole,
    PostAnalysisKnowledgeRefreshInput,
    ProjectCreate,
    ProjectProfileSnapshot,
    ProjectProfileStatus,
    ProjectProfileWorkflowInput,
    ProjectRepository,
    ProjectRunRequest,
    ProjectWorkflowProgress,
    ProjectWorkflowStage,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProjectWorkflowTaskStatus,
    ProviderKind,
    RetiredChangeAnalysisWorkflowInput,
    RunMode,
)
from guidesync_agent.services import workflow_executor as workflow_executor_module
from guidesync_agent.services.workflow_executor import ProjectWorkflowExecutor
from guidesync_agent.services.workflow_planner import ProjectWorkflowPlanner
from guidesync_agent.storage import (
    DatabaseProjectStore,
    DatabaseProjectWorkflowStore,
    DatabaseRunStore,
    create_llm_transcript_store,
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
    assert plan.run.status == "planning"
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
    assert DatabaseRunStore(database_url).claim_next_queued_run() is None


def test_planner_expands_selected_branches_into_independent_inputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = sqlite_database_url(tmp_path / "branch-planner.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    project = DatabaseProjectStore(database_url).save(
        ProjectCreate(
            name="Branch planner project",
            repositories=[
                ProjectRepository(
                    id="repo-branches",
                    name="fixture",
                    url="https://github.com/example/repo",
                    default_branch="main",
                    analysis_paths=["src"],
                )
            ],
        )
    )

    plan = ProjectWorkflowPlanner().enqueue_change_analysis_pipeline(
        project.id,
        ProjectRunRequest(
            mode=RunMode.SELECT_BRANCHES,
            goal="Write branch release notes.",
            branches={"repo-branches": ["feature/one", "feature/two"]},
        ),
    )

    assert plan is not None
    assert plan.run is not None
    stored = DatabaseRunStore(database_url).get(plan.run.run_id)
    assert stored is not None
    assert [repository.name for repository in stored.request.repositories] == [
        "fixture [feature/one]",
        "fixture [feature/two]",
    ]
    assert [repository.ref for repository in stored.request.repositories] == ["main", "main"]
    assert [repository.branches for repository in stored.request.repositories] == [
        ["feature/one"],
        ["feature/two"],
    ]
    assert all(repository.since is None for repository in stored.request.repositories)


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
    unit_tasks = [store.enqueue(analysis_unit_task("project-units", index)) for index in range(5)]
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
        tasks[item.id].status is ProjectWorkflowTaskStatus.COMPLETED for item in unit_tasks[:4]
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


def test_workflow_heartbeat_persists_visible_progress(monkeypatch, tmp_path: Path) -> None:
    database_url = sqlite_database_url(tmp_path / "workflow-progress.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    store = DatabaseProjectWorkflowStore(database_url)
    store.enqueue(analysis_unit_task("project-progress", 1))
    claimed = store.claim_next()

    assert claimed is not None
    assert claimed.lease_token is not None
    updated = store.heartbeat(
        claimed.id,
        claimed.lease_token,
        ProjectWorkflowProgress(
            stage=ProjectWorkflowStage.ANALYZING,
            message="Analyzing one cohesive group",
            total_items=1,
        ),
    )
    visible = store.get(claimed.id)

    assert updated is True
    assert visible is not None
    assert visible.progress.stage is ProjectWorkflowStage.ANALYZING
    assert visible.progress.message == "Analyzing one cohesive group"
    assert visible.last_heartbeat_at is not None


def test_completing_task_keeps_final_heartbeat_fresh(monkeypatch, tmp_path: Path) -> None:
    database_url = sqlite_database_url(tmp_path / "workflow-completed-heartbeat.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    store = DatabaseProjectWorkflowStore(database_url)
    store.enqueue(analysis_unit_task("project-progress", 1))
    claimed = store.claim_next()

    assert claimed is not None
    assert claimed.lease_token is not None
    assert store.heartbeat(claimed.id, claimed.lease_token) is True
    visible = store.get(claimed.id)
    completed = workflow_executor_module.save_completed_task(claimed)

    assert visible is not None
    assert visible.last_heartbeat_at is not None
    assert completed.last_heartbeat_at is not None
    assert completed.last_heartbeat_at == completed.completed_at


def test_cancel_run_terminalizes_unfinished_graph_and_preserves_completed_tasks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = sqlite_database_url(tmp_path / "workflow-cancel.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    project = DatabaseProjectStore(database_url).save(
        ProjectCreate(
            name="Cancellation project",
            repositories=[
                ProjectRepository(
                    id="repo-cancel",
                    name="fixture",
                    url="https://github.com/example/repo",
                    default_branch="main",
                )
            ],
        )
    )
    plan = ProjectWorkflowPlanner().enqueue_change_analysis_pipeline(
        project.id,
        ProjectRunRequest(goal="Cancel this analysis."),
    )
    assert plan is not None and plan.run is not None
    run_id = plan.run.run_id
    store = DatabaseProjectWorkflowStore(database_url)
    plan_task = next(
        task for task in plan.tasks if task.kind is ProjectWorkflowTaskKind.CHANGE_ANALYSIS_PLAN
    )
    store.save(plan_task.model_copy(update={"status": ProjectWorkflowTaskStatus.COMPLETED}))
    unit = store.enqueue(analysis_unit_task(project.id, 1, run_id=run_id))
    store.save(unit.model_copy(update={"status": ProjectWorkflowTaskStatus.RUNNING}))
    synthesis = store.enqueue(
        ProjectWorkflowTask(
            project_id=project.id,
            kind=ProjectWorkflowTaskKind.CHANGE_SYNTHESIS,
            depends_on_task_ids=[unit.id],
            input=ChangeSynthesisWorkflowInput(
                run_id=run_id,
                plan_task_id=plan_task.id,
                unit_task_ids=[unit.id],
            ),
        )
    )
    transcript_store = create_llm_transcript_store()
    transcript = transcript_store.save(
        LLMConversationTranscript(
            project_id=project.id,
            run_id=run_id,
            workflow_task_id=unit.id,
            model_role=ModelRole.CODE_CHANGE_ANALYSIS,
            provider=ProviderKind.PYDANTIC_AI,
            model="test-model",
            conversation_id=f"conversation:{run_id}",
            status=LLMConversationStatus.PARTIAL,
        )
    )

    result = store.cancel_run(run_id, reason="Cancelled in test.")

    assert result.run.status == "cancelled"
    assert plan_task.id in result.preserved_completed_task_ids
    assert set(result.cancelled_task_ids) == {unit.id, synthesis.id}
    assert result.cancelled_transcript_ids == [transcript.id]
    saved_plan = store.get(plan_task.id)
    saved_unit = store.get(unit.id)
    assert saved_plan is not None
    assert saved_unit is not None
    assert saved_plan.status is ProjectWorkflowTaskStatus.COMPLETED
    assert saved_unit.status is ProjectWorkflowTaskStatus.CANCELLED
    saved_transcript = transcript_store.get(transcript.id)
    assert saved_transcript is not None
    assert saved_transcript.status is LLMConversationStatus.CANCELLED


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
    store.save(old_task.model_copy(update={"status": ProjectWorkflowTaskStatus.RUNNING}))

    claimed = store.claim_next()
    assert claimed is not None
    saved = asyncio.run(ProjectWorkflowExecutor().execute(claimed))

    assert saved.status is ProjectWorkflowTaskStatus.FAILED
    assert saved.error_message == "Unsupported workflow task kind: change_analysis"


def analysis_unit_task(
    project_id: str,
    index: int,
    *,
    run_id: str = "run-units",
) -> ProjectWorkflowTask:
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
        input=ChangeAnalysisUnitWorkflowInput(run_id=run_id, work_unit=unit),
    )
