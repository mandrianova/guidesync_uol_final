import asyncio
from types import SimpleNamespace

import pytest

from guidesync_agent.schemas import (
    ChangeAnalysisUnitWorkflowInput,
    ChangeAnalysisUnitWorkflowResult,
    ChangeAnalysisWorkUnit,
    ChangedFileRef,
    ChangeSynthesisWorkflowInput,
    EvidenceBundle,
    FileChangeSummary,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
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
