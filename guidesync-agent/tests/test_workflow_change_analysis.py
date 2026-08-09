import asyncio
from types import SimpleNamespace

import pytest

from guidesync_agent.schemas import (
    ChangeAnalysisPlanWorkflowInput,
    ChangeAnalysisPlanWorkflowResult,
    ChangeAnalysisUnitWorkflowInput,
    ChangeAnalysisUnitWorkflowResult,
    ChangeAnalysisWorkUnit,
    ChangedFileRef,
    ChangeSynthesisWorkflowInput,
    CommitEvidence,
    EvidenceBundle,
    FileChangeSummary,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    RepositoryInput,
)
from guidesync_agent.services import workflow_change_analysis
from guidesync_agent.services.workflow_change_analysis import build_analysis_manifest


def test_analysis_manifest_carries_compact_file_digest() -> None:
    work_unit = ChangeAnalysisWorkUnit(
        id="unit-1",
        repository_id="repo-1",
        files=[ChangedFileRef(path="src/app.py", status="M")],
        grouping_reason="related implementation",
    )
    summary = FileChangeSummary(
        repository_id="repo-1",
        path="src/app.py",
        status="M",
        technical_summary="Streams rows incrementally.",
        product_impact="Developers can return a streamed response.",
        affected_components=["routing"],
        documentation_search_intents=["streaming response"],
        evidence_refs=["diff:repo-1:src/app.py"],
        artifact_uri="/tmp/file-summary.json",
    )
    unit_task = ProjectWorkflowTask(
        project_id="project-1",
        kind=ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT,
        input=ChangeAnalysisUnitWorkflowInput(run_id="run-1", work_unit=work_unit),
        result=ChangeAnalysisUnitWorkflowResult(
            work_unit_id=work_unit.id,
            file_summaries=[summary],
        ),
    )

    manifest = build_analysis_manifest(
        ChangeSynthesisWorkflowInput(
            run_id="run-1",
            plan_task_id="plan-1",
            unit_task_ids=[unit_task.id],
        ),
        [unit_task],
    )

    assert len(manifest.artifacts) == 1
    digest = manifest.artifacts[0].digest
    assert digest.technical_summary == "Streams rows incrementally."
    assert digest.affected_components == ["routing"]
    assert digest.evidence_refs == ["diff:repo-1:src/app.py"]


def test_analysis_plan_does_not_enqueue_redundant_full_reindex(monkeypatch) -> None:
    request = GuideSyncRunRequest(run_id="run-1", goal="Draft documentation.")
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="running",
        request=request,
        evidence=EvidenceBundle(),
    )
    parent = ProjectWorkflowTask(
        project_id="project-1",
        kind=ProjectWorkflowTaskKind.CHANGE_ANALYSIS_PLAN,
        input=ChangeAnalysisPlanWorkflowInput(run_id=run.run_id),
    )
    work_unit = ChangeAnalysisWorkUnit(
        id="unit-1",
        repository_id="repo-1",
        files=[ChangedFileRef(path="src/app.py", status="M")],
        grouping_reason="related implementation",
    )

    class WorkflowStore:
        def __init__(self) -> None:
            self.enqueued = []

        def enqueue(self, task):
            self.enqueued.append(task)
            return task

    store = WorkflowStore()
    monkeypatch.setattr(workflow_change_analysis, "require_workflow_run", lambda _: run)
    monkeypatch.setattr(workflow_change_analysis, "mark_analysis_run_started", lambda _: run)
    monkeypatch.setattr(
        workflow_change_analysis,
        "collect_change_analysis_plan",
        lambda _: ([work_unit], [{"repository_id": "repo-1", "path": "src/app.py"}]),
    )
    monkeypatch.setattr(
        workflow_change_analysis,
        "write_workflow_artifact",
        lambda *args, **kwargs: "/tmp/change-analysis-plan.json",
    )
    monkeypatch.setattr(
        workflow_change_analysis,
        "create_project_workflow_store",
        lambda: store,
    )

    completed = workflow_change_analysis.execute_change_analysis_plan(parent)
    result = ChangeAnalysisPlanWorkflowResult.model_validate(completed.result)

    assert [task.kind for task in store.enqueued] == [
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT,
        ProjectWorkflowTaskKind.CHANGE_SYNTHESIS,
    ]
    assert result.refresh_task_id is None


def test_analysis_plan_uses_historical_evidence_refs(monkeypatch) -> None:
    repository = RepositoryInput(
        name="starlight",
        project_id="project-1",
        repository_id="repo-1",
        until="2025-04-08",
    )
    request = GuideSyncRunRequest(
        run_id="run-historical",
        goal="Document the selected historical change.",
        repositories=[repository],
    )
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="running",
        request=request,
        evidence=EvidenceBundle(),
    )
    evidence = EvidenceBundle(
        commits=[
            CommitEvidence(
                repo="starlight",
                sha="selected-sha",
                short_sha="selected",
                date="2025-04-07",
                subject="Selected historical change",
            )
        ]
    )
    observed = {}

    monkeypatch.setattr(workflow_change_analysis, "collect_evidence", lambda *_: evidence)
    monkeypatch.setattr(
        workflow_change_analysis,
        "create_run_store",
        lambda: SimpleNamespace(save=lambda result: observed.update(saved=result)),
    )

    def list_files(project_id, repository_id, *, base_ref=None, head_ref="HEAD"):
        observed.update(
            project_id=project_id,
            repository_id=repository_id,
            base_ref=base_ref,
            head_ref=head_ref,
        )
        return SimpleNamespace(
            error=None,
            files=[ChangedFileRef(path="MobileMenuToggle.astro", status="M")],
            base_ref=base_ref,
            head_ref=head_ref,
        )

    monkeypatch.setattr(workflow_change_analysis, "list_changed_files", list_files)

    units, changed_files = workflow_change_analysis.collect_change_analysis_plan(run)

    assert observed["base_ref"] == "selected-sha^"
    assert observed["head_ref"] == "selected-sha"
    assert observed["saved"].evidence.commits == evidence.commits
    assert units[0].files[0].path == "MobileMenuToggle.astro"
    assert changed_files[0]["path"] == "MobileMenuToggle.astro"


def test_failed_synthesis_stops_before_knowledge_refresh(monkeypatch, tmp_path) -> None:
    request = GuideSyncRunRequest(run_id="run-1", goal="Draft documentation.")
    request.report.output_dir = tmp_path
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="running",
        request=request,
        evidence=EvidenceBundle(),
    )
    task = ProjectWorkflowTask(
        project_id="project-1",
        kind=ProjectWorkflowTaskKind.CHANGE_SYNTHESIS,
        input=ChangeSynthesisWorkflowInput(
            run_id=run.run_id,
            plan_task_id="plan-1",
            unit_task_ids=[],
        ),
    )

    monkeypatch.setattr(workflow_change_analysis, "require_workflow_run", lambda _: run)
    monkeypatch.setattr(
        workflow_change_analysis,
        "prepare_documentation_update_from_summaries",
        lambda *args, **kwargs: SimpleNamespace(),
    )

    async def failed_run(*args, **kwargs):
        return run.model_copy(update={"status": "failed"})

    monkeypatch.setattr(workflow_change_analysis, "run_guidesync", failed_run)

    with pytest.raises(RuntimeError, match="knowledge refresh was skipped"):
        asyncio.run(workflow_change_analysis.execute_change_synthesis(task))
