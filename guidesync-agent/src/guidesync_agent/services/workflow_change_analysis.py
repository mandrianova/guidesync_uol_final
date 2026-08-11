from __future__ import annotations

from guidesync_agent.evidence import collect_evidence
from guidesync_agent.pipeline import run_guidesync, save_run_state
from guidesync_agent.schemas import (
    AnalysisArtifactDigest,
    AnalysisArtifactManifest,
    AnalysisArtifactRef,
    ChangeAnalysisPlanWorkflowInput,
    ChangeAnalysisPlanWorkflowResult,
    ChangeAnalysisUnitWorkflowInput,
    ChangeAnalysisUnitWorkflowResult,
    ChangeAnalysisWorkUnit,
    ChangeSynthesisWorkflowInput,
    ChangeSynthesisWorkflowResult,
    FileChangeSummary,
    GuideSyncRunResult,
    ProjectWorkflowProgress,
    ProjectWorkflowStage,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProjectWorkflowTaskStatus,
    ValidationFinding,
)
from guidesync_agent.storage import create_project_workflow_store, create_run_store
from guidesync_agent.tools.repository import list_changed_files
from guidesync_agent.workflows.documentation_update import (
    historical_analysis_refs,
    prepare_documentation_update_from_summaries,
    project_profile_for_request,
    write_file_summary_artifact,
    write_workflow_artifact,
)

from .change_analysis import ChangeAnalysisContext, summarize_change_group
from .change_analysis_planning import build_change_analysis_work_units
from .video_presentation import enqueue_video_presentation


def execute_change_analysis_plan(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    task_input = ChangeAnalysisPlanWorkflowInput.model_validate(task.input)
    run = mark_analysis_run_started(require_workflow_run(task_input.run_id))
    units, changed_files = collect_change_analysis_plan(run)
    plan_artifact_ref = write_workflow_artifact(
        run.request.report.output_dir / "workflow" / "change-analysis-plan.json",
        {
            "run_id": run.run_id,
            "plan_task_id": task.id,
            "changed_files": changed_files,
            "work_units": [unit.model_dump(mode="json") for unit in units],
        },
    )
    unit_tasks = enqueue_analysis_units(task, run.run_id, units)
    synthesis = enqueue_synthesis(task, run.run_id, unit_tasks)
    result = ChangeAnalysisPlanWorkflowResult(
        work_units=units,
        unit_task_ids=[item.id for item in unit_tasks],
        synthesis_task_id=synthesis.id,
        manifest_artifact_ref=plan_artifact_ref,
    )
    return task.model_copy(update={"result": result})


def mark_analysis_run_started(run: GuideSyncRunResult) -> GuideSyncRunResult:
    if run.status not in {"queued", "planning"}:
        return run
    running = run.model_copy(update={"status": "running"})
    store = create_run_store()
    store.save(running)
    store.record_run_event(
        run.run_id,
        "running",
        "Change analysis planning started.",
        "planning",
    )
    return running


def collect_change_analysis_plan(
    run: GuideSyncRunResult,
) -> tuple[list[ChangeAnalysisWorkUnit], list[dict[str, object]]]:
    evidence = collect_evidence(run.request.repositories, run.request.documentation)
    create_run_store().save(run.model_copy(update={"evidence": evidence}))
    units = []
    changed_files = []
    for repository in run.request.repositories:
        if not repository.project_id or not repository.repository_id:
            continue
        base_ref, head_ref = historical_analysis_refs(repository, evidence)
        result = list_changed_files(
            repository.project_id,
            repository.repository_id,
            base_ref=base_ref,
            head_ref=head_ref,
        )
        if result.error is not None:
            raise RuntimeError(result.error.message)
        changed_files.extend(
            {"repository_id": repository.repository_id, **item.model_dump(mode="json")}
            for item in result.files
        )
        units.extend(
            build_change_analysis_work_units(
                repository.repository_id,
                result.files,
                base_ref=result.base_ref,
                head_ref=result.head_ref,
            )
        )
    return units, changed_files


def enqueue_analysis_units(
    parent: ProjectWorkflowTask,
    run_id: str,
    units: list[ChangeAnalysisWorkUnit],
) -> list[ProjectWorkflowTask]:
    store = create_project_workflow_store()
    return [
        store.enqueue(
            ProjectWorkflowTask(
                project_id=parent.project_id,
                kind=ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT,
                depends_on_task_ids=[parent.id],
                dedupe_key=f"change_analysis_unit:{run_id}:{unit.id}",
                requested_by=parent.requested_by,
                reason="analyze_changed_files",
                input=ChangeAnalysisUnitWorkflowInput(run_id=run_id, work_unit=unit),
            )
        )
        for unit in units
    ]


def enqueue_synthesis(
    parent: ProjectWorkflowTask,
    run_id: str,
    unit_tasks: list[ProjectWorkflowTask],
) -> ProjectWorkflowTask:
    return create_project_workflow_store().enqueue(
        ProjectWorkflowTask(
            project_id=parent.project_id,
            kind=ProjectWorkflowTaskKind.CHANGE_SYNTHESIS,
            depends_on_task_ids=[item.id for item in unit_tasks] or [parent.id],
            dedupe_key=f"change_synthesis:{run_id}",
            requested_by=parent.requested_by,
            reason="synthesize_change_analysis",
            input=ChangeSynthesisWorkflowInput(
                run_id=run_id,
                plan_task_id=parent.id,
                unit_task_ids=[item.id for item in unit_tasks],
            ),
        )
    )


def execute_change_analysis_unit(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    task_input = ChangeAnalysisUnitWorkflowInput.model_validate(task.input)
    run = require_workflow_run(task_input.run_id)
    work_unit = task_input.work_unit
    project_profile = project_profile_for_request(run.request, task.project_id)
    output_dir = run.request.report.output_dir / "workflow" / "analysis-units" / work_unit.id
    context = ChangeAnalysisContext(
        project_id=task.project_id,
        repository_id=work_unit.repository_id,
        run_id=run.run_id,
        workflow_task_id=task.id,
        goal=run.request.goal,
        audience=run.request.audience.value,
        project_profile=project_profile,
        knowledge_context_enabled=run.request.context_sources.knowledge_base,
        base_ref=work_unit.base_ref,
        head_ref=work_unit.head_ref,
    )
    analysis_progress = ProjectWorkflowProgress(
        stage=ProjectWorkflowStage.ANALYZING,
        message=f"Analyzing {len(work_unit.files)} related changed files",
        total_items=len(work_unit.files),
    )
    if task.lease_token:
        create_project_workflow_store().heartbeat(task.id, task.lease_token, analysis_progress)
    summaries = [
        write_file_summary_artifact(
            output_dir,
            summary,
        )
        for summary in summarize_change_group(
            context,
            work_unit.files,
            work_unit_id=work_unit.id,
            grouping_reason=work_unit.grouping_reason,
            connectivity_evidence=work_unit.connectivity_evidence,
        )
    ]
    result = ChangeAnalysisUnitWorkflowResult(
        work_unit_id=work_unit.id,
        file_summaries=summaries,
    )
    return task.model_copy(
        update={
            "result": result,
            "progress": analysis_progress.model_copy(
                update={"completed_items": len(work_unit.files)}
            ),
        }
    )


async def execute_change_synthesis(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    task_input = ChangeSynthesisWorkflowInput.model_validate(task.input)
    run = require_workflow_run(task_input.run_id)
    unit_tasks = [require_completed_workflow_task(item) for item in task_input.unit_task_ids]
    summaries = unit_summaries(unit_tasks)
    manifest = build_analysis_manifest(task_input, unit_tasks)
    manifest_ref = write_workflow_artifact(
        run.request.report.output_dir / "workflow" / "analysis-manifest.json",
        manifest.model_dump(mode="json"),
    )
    context = prepare_documentation_update_from_summaries(
        run.request,
        summaries,
        unit_changed_files(unit_tasks),
        artifacts={"analysis-manifest.json": manifest_ref},
    )
    result = await run_guidesync(
        run.request,
        workflow_task_id=task.id,
        workflow_context=context,
        analysis_manifest=manifest,
    )
    if result.status == "failed":
        raise RuntimeError(
            "Release-note synthesis failed; post-analysis knowledge refresh was skipped."
        )
    video_task = enqueue_video_presentation(task, result.run_id)
    return task.model_copy(
        update={
            "result": ChangeSynthesisWorkflowResult(
                report_run_id=result.run_id,
                video_presentation_task_id=video_task.id if video_task else None,
            )
        }
    )


def unit_summaries(unit_tasks: list[ProjectWorkflowTask]) -> list[FileChangeSummary]:
    return [
        summary
        for unit_task in unit_tasks
        for summary in ChangeAnalysisUnitWorkflowResult.model_validate(
            unit_task.result
        ).file_summaries
    ]


def unit_changed_files(unit_tasks: list[ProjectWorkflowTask]) -> list[dict[str, object]]:
    return [
        {"repository_id": unit_input.work_unit.repository_id, **item.model_dump(mode="json")}
        for unit_task in unit_tasks
        for unit_input in [ChangeAnalysisUnitWorkflowInput.model_validate(unit_task.input)]
        for item in unit_input.work_unit.files
    ]


def build_analysis_manifest(
    task_input: ChangeSynthesisWorkflowInput,
    unit_tasks: list[ProjectWorkflowTask],
) -> AnalysisArtifactManifest:
    unit_results = [
        ChangeAnalysisUnitWorkflowResult.model_validate(item.result) for item in unit_tasks
    ]
    artifacts = [
        AnalysisArtifactRef(
            id=summary.id,
            work_unit_id=result.work_unit_id,
            repository_id=summary.repository_id,
            path=summary.path,
            artifact_ref=summary.artifact_uri,
            digest=AnalysisArtifactDigest(
                technical_summary=summary.technical_summary,
                product_impact=summary.product_impact,
                affected_components=summary.affected_components,
                affected_workflows=summary.affected_workflows,
                documentation_search_intents=summary.documentation_search_intents,
                risk_notes=summary.risk_notes,
                evidence_refs=summary.evidence_refs,
                needs_main_agent_review=summary.needs_main_agent_review,
            ),
        )
        for result in unit_results
        for summary in result.file_summaries
        if summary.artifact_uri
    ]
    return AnalysisArtifactManifest(
        run_id=task_input.run_id,
        plan_task_id=task_input.plan_task_id,
        planned_paths=[
            f"{unit_input.work_unit.repository_id}:{item.path}"
            for unit_task in unit_tasks
            for unit_input in [ChangeAnalysisUnitWorkflowInput.model_validate(unit_task.input)]
            for item in unit_input.work_unit.files
        ],
        completed_unit_ids=[result.work_unit_id for result in unit_results],
        artifacts=artifacts,
    )


def require_workflow_run(run_id: str) -> GuideSyncRunResult:
    run = create_run_store().get(run_id)
    if run is None:
        raise ValueError(f"Workflow run not found: {run_id}")
    return run


def require_completed_workflow_task(task_id: str) -> ProjectWorkflowTask:
    task = create_project_workflow_store().get(task_id)
    if task is None:
        raise ValueError(f"Workflow task not found: {task_id}")
    if task.status is not ProjectWorkflowTaskStatus.COMPLETED:
        raise ValueError(f"Workflow task is not completed: {task_id}")
    return task


def fail_analysis_run(task: ProjectWorkflowTask, message: str) -> None:
    analysis_kinds = {
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS_PLAN,
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT,
        ProjectWorkflowTaskKind.CHANGE_SYNTHESIS,
    }
    run_id = getattr(task.input, "run_id", None)
    if task.kind not in analysis_kinds or not isinstance(run_id, str):
        return
    run = create_run_store().get(run_id)
    if run is None:
        return
    if run.status == "failed":
        return
    save_run_state(
        run.request,
        "failed",
        [ValidationFinding(severity="error", check="workflow", message=message)],
    )
