from __future__ import annotations

from pathlib import Path

from guidesync_agent.schemas import (
    KnowledgeIndexWorkflowInput,
    ProjectCreate,
    ProjectRepository,
    ProjectRunRequest,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProjectWorkflowTaskStatus,
    ProviderConfig,
    ProviderKind,
)
from guidesync_agent.services.workflow_planner import ProjectWorkflowPlanner
from guidesync_agent.storage import (
    DatabaseProjectStore,
    DatabaseProjectWorkflowStore,
    create_project_workflow_store,
)


def test_workflow_store_claims_fifo_inside_project(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'workflow.db'}")
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
    database_url = f"sqlite+pysqlite:///{tmp_path / 'planner.db'}"
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    DatabaseProjectWorkflowStore(database_url).initialize()
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
