from __future__ import annotations

from guidesync_agent.agent_runtime.change_analysis_orchestrator import (
    run_change_analysis_orchestrator,
)
from guidesync_agent.pipeline import run_guidesync
from guidesync_agent.schemas import (
    AnalysisArtifactDigest,
    AnalysisArtifactManifest,
    AnalysisArtifactRef,
    ChangeAnalysisCheckpoint,
    ChangeAnalysisInventory,
    ChangeAnalysisInventoryItem,
    ChangeAnalysisInventoryItemKind,
    ChangeAnalysisPlanWorkflowInput,
    ChangeAnalysisPlanWorkflowResult,
    ChangeAnalysisUnitWorkflowInput,
    ChangeAnalysisWorkflowInput,
    ChangeAnalysisWorkflowResult,
    ChangeSynthesisWorkflowInput,
    ChangeSynthesisWorkflowResult,
    FileChangeSummary,
    GuideSyncRunResult,
    ProjectWorkflowProgress,
    ProjectWorkflowStage,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProjectWorkflowTaskStatus,
    ReleaseChangeConfidence,
    ReleaseChangeFinding,
    ScreenshotCaptureWorkflowInput,
    ScreenshotPolicy,
    ValidationFinding,
)
from guidesync_agent.storage import create_project_workflow_store, create_run_store
from guidesync_agent.tools.change_analysis_orchestrator import (
    ChangeAnalysisOrchestratorDeps,
)
from guidesync_agent.workflows.documentation_update import (
    prepare_documentation_update_from_summaries,
    write_workflow_artifact,
)

from .change_inventory import collect_change_analysis_inventory


def execute_change_analysis_plan(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    task_input = ChangeAnalysisPlanWorkflowInput.model_validate(task.input)
    run = mark_analysis_run_started(require_workflow_run(task_input.run_id))
    inventory = collect_change_analysis_inventory(run)
    plan_artifact_ref = write_workflow_artifact(
        run.request.report.output_dir / "workflow" / "change-analysis-plan.json",
        {
            "run_id": run.run_id,
            "plan_task_id": task.id,
            "inventory": inventory.model_dump(mode="json"),
        },
    )
    analysis, synthesis = enqueue_analysis_and_synthesis(task, inventory)
    result = ChangeAnalysisPlanWorkflowResult(
        inventory=inventory,
        analysis_task_id=analysis.id,
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
        "Change inventory collection started.",
        "planning",
    )
    return running


def enqueue_analysis_and_synthesis(
    parent: ProjectWorkflowTask,
    inventory: ChangeAnalysisInventory,
) -> tuple[ProjectWorkflowTask, ProjectWorkflowTask]:
    store = create_project_workflow_store()
    analysis = store.enqueue(
        ProjectWorkflowTask(
            project_id=parent.project_id,
            kind=ProjectWorkflowTaskKind.CHANGE_ANALYSIS,
            depends_on_task_ids=[parent.id],
            dedupe_key=f"change_analysis_orchestration:{inventory.run_id}",
            requested_by=parent.requested_by,
            reason="analyze_changes_semantically",
            input=ChangeAnalysisWorkflowInput(
                run_id=inventory.run_id,
                plan_task_id=parent.id,
            ),
        )
    )
    synthesis = store.enqueue(
        ProjectWorkflowTask(
            project_id=parent.project_id,
            kind=ProjectWorkflowTaskKind.CHANGE_SYNTHESIS,
            depends_on_task_ids=[analysis.id],
            dedupe_key=f"change_synthesis:{inventory.run_id}",
            requested_by=parent.requested_by,
            reason="synthesize_change_analysis",
            input=ChangeSynthesisWorkflowInput(
                run_id=inventory.run_id,
                plan_task_id=parent.id,
                analysis_task_id=analysis.id,
            ),
        )
    )
    return analysis, synthesis


def execute_change_analysis(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    task_input = ChangeAnalysisWorkflowInput.model_validate(task.input)
    run = require_workflow_run(task_input.run_id)
    plan_task = require_completed_workflow_task(task_input.plan_task_id)
    plan_result = ChangeAnalysisPlanWorkflowResult.model_validate(plan_task.result)
    if plan_result.inventory is None:
        raise ValueError("Change-analysis plan has no frozen inventory.")
    existing = (
        ChangeAnalysisWorkflowResult.model_validate(task.result)
        if task.result is not None
        else None
    )
    deps = ChangeAnalysisOrchestratorDeps(
        project_id=task.project_id,
        run_id=run.run_id,
        workflow_task_id=task.id,
        inventory=plan_result.inventory,
        checkpoint=(existing.checkpoint if existing else ChangeAnalysisCheckpoint()),
        audience=run.request.audience.value,
    )
    result = run_change_analysis_orchestrator(deps)
    artifact_ref = write_workflow_artifact(
        run.request.report.output_dir / "workflow" / "release-change-findings.json",
        result.model_dump(mode="json"),
    )
    result.checkpoint.findings = [
        finding.model_copy(update={"artifact_ref": artifact_ref})
        for finding in result.checkpoint.findings
    ]
    return task.model_copy(
        update={
            "result": result,
            "progress": ProjectWorkflowProgress(
                stage=ProjectWorkflowStage.ANALYZING,
                message="Semantic change analysis completed",
                completed_items=len(result.inventory.items),
                total_items=len(result.inventory.items),
            ),
        }
    )


def execute_change_analysis_unit(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    """Fail clearly if a queued task from the removed file-batch workflow is claimed."""
    ChangeAnalysisUnitWorkflowInput.model_validate(task.input)
    raise RuntimeError(
        "File-batch change analysis has been removed; retry the report to create a semantic run."
    )


async def execute_change_synthesis(task: ProjectWorkflowTask) -> ProjectWorkflowTask:
    task_input = ChangeSynthesisWorkflowInput.model_validate(task.input)
    run = require_workflow_run(task_input.run_id)
    analysis_task = require_analysis_task(task_input)
    analysis_result = ChangeAnalysisWorkflowResult.model_validate(analysis_task.result)
    if not analysis_result.checkpoint.completed:
        raise RuntimeError("Change analysis is incomplete; release-note synthesis was skipped.")
    manifest = build_analysis_manifest(task_input, analysis_task)
    manifest_ref = write_workflow_artifact(
        run.request.report.output_dir / "workflow" / "analysis-manifest.json",
        manifest.model_dump(mode="json"),
    )
    artifacts = {"analysis-manifest.json": manifest_ref}
    if findings_ref := finding_artifact_ref(analysis_result):
        artifacts["release-change-findings.json"] = run.artifacts.get(
            "release-change-findings.json",
            findings_ref,
        )
    context = prepare_documentation_update_from_summaries(
        run.request,
        finding_summaries(analysis_result),
        inventory_changed_files(analysis_result.inventory),
        artifacts=artifacts,
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
    screenshot_task = enqueue_optional_screenshot_capture(task, result)
    return task.model_copy(
        update={
            "result": ChangeSynthesisWorkflowResult(
                report_run_id=result.run_id,
                screenshot_task_id=screenshot_task.id if screenshot_task else None,
            )
        }
    )


def enqueue_optional_screenshot_capture(
    synthesis_task: ProjectWorkflowTask,
    run: GuideSyncRunResult,
) -> ProjectWorkflowTask | None:
    if (
        run.request.screenshot_policy is ScreenshotPolicy.DISABLED
        or not (run.request.task_interface_url or "").strip()
        or run.update is None
        or not run.update.screenshot_requests
    ):
        return None
    return create_project_workflow_store().enqueue(
        ProjectWorkflowTask(
            project_id=synthesis_task.project_id,
            kind=ProjectWorkflowTaskKind.SCREENSHOT_CAPTURE,
            depends_on_task_ids=[synthesis_task.id],
            dedupe_key=f"screenshot_capture:{run.run_id}",
            requested_by=synthesis_task.requested_by,
            reason="capture_optional_report_screenshots",
            input=ScreenshotCaptureWorkflowInput(
                run_id=run.run_id,
                synthesis_task_id=synthesis_task.id,
            ),
        )
    )


def require_analysis_task(task_input: ChangeSynthesisWorkflowInput) -> ProjectWorkflowTask:
    if task_input.analysis_task_id is None:
        raise ValueError(
            "Legacy file-unit synthesis is no longer supported; retry the report."
        )
    task = require_completed_workflow_task(task_input.analysis_task_id)
    if task.kind is not ProjectWorkflowTaskKind.CHANGE_ANALYSIS:
        raise ValueError(f"Workflow task is not semantic change analysis: {task.id}")
    return task


def build_analysis_manifest(
    task_input: ChangeSynthesisWorkflowInput,
    analysis_task: ProjectWorkflowTask,
) -> AnalysisArtifactManifest:
    result = ChangeAnalysisWorkflowResult.model_validate(analysis_task.result)
    artifacts = [
        finding_artifact_ref_entry(finding, result.inventory)
        for finding in result.checkpoint.findings
        if finding.artifact_ref
    ]
    return AnalysisArtifactManifest(
        run_id=task_input.run_id,
        plan_task_id=task_input.plan_task_id,
        planned_paths=[
            f"{item.repository_id}:{item.path}"
            for item in result.inventory.items
            if item.kind is ChangeAnalysisInventoryItemKind.PATH and item.path
        ],
        completed_unit_ids=[analysis_task.id],
        artifacts=artifacts,
        findings=result.checkpoint.findings,
        coverage=result.checkpoint.coverage,
    )


def finding_artifact_ref_entry(
    finding: ReleaseChangeFinding,
    inventory: ChangeAnalysisInventory,
) -> AnalysisArtifactRef:
    item = representative_inventory_item(finding, inventory)
    return AnalysisArtifactRef(
        id=finding.id,
        work_unit_id=finding.id,
        repository_id=item.repository_id,
        path=item.path or item.commit_sha or finding.id,
        artifact_ref=finding.artifact_ref or "",
        digest=AnalysisArtifactDigest(
            technical_summary=finding.technical_summary,
            product_impact=finding.user_impact,
            documentation_search_intents=finding.documentation_search_intents,
            risk_notes=finding.risk_notes,
            evidence_refs=finding.evidence_refs,
            needs_main_agent_review=finding.confidence is ReleaseChangeConfidence.LOW,
        ),
    )


def finding_summaries(result: ChangeAnalysisWorkflowResult) -> list[FileChangeSummary]:
    return [
        finding_summary(finding, result.inventory)
        for finding in result.checkpoint.findings
        if finding.release_note_eligible
    ]


def finding_summary(
    finding: ReleaseChangeFinding,
    inventory: ChangeAnalysisInventory,
) -> FileChangeSummary:
    item = representative_inventory_item(finding, inventory)
    return FileChangeSummary(
        id=finding.id,
        repository_id=item.repository_id,
        path=item.path or item.commit_sha or finding.id,
        status=item.status or "M",
        technical_summary=finding.technical_summary,
        product_impact=finding.user_impact,
        documentation_keywords=finding.documentation_search_intents,
        docs_to_search=finding.documentation_search_intents,
        risk_notes=finding.risk_notes,
        what_changed=finding.title,
        documentation_search_intents=finding.documentation_search_intents,
        evidence_refs=finding.evidence_refs,
        needs_main_agent_review=finding.confidence is ReleaseChangeConfidence.LOW,
        artifact_uri=finding.artifact_ref,
    )


def representative_inventory_item(
    finding: ReleaseChangeFinding,
    inventory: ChangeAnalysisInventory,
) -> ChangeAnalysisInventoryItem:
    by_key = {item.key: item for item in inventory.items}
    candidates = [by_key[key] for key in finding.coverage_keys if key in by_key]
    path_item = next((item for item in candidates if item.path), None)
    if path_item is not None:
        return path_item
    if candidates:
        return candidates[0]
    raise ValueError(f"Finding has no inventory coverage: {finding.id}")


def inventory_changed_files(
    inventory: ChangeAnalysisInventory,
) -> list[dict[str, object]]:
    changed_files: dict[tuple[str, str], dict[str, object]] = {}
    for item in inventory.items:
        if item.kind is ChangeAnalysisInventoryItemKind.PATH and item.path:
            changed_files[(item.repository_id, item.path)] = {
                "repository_id": item.repository_id,
                "path": item.path,
                "status": item.status or "M",
            }
            continue
        for path in item.related_paths:
            changed_files.setdefault(
                (item.repository_id, path),
                {
                    "repository_id": item.repository_id,
                    "path": path,
                    "status": "M",
                },
            )
    return list(changed_files.values())


def finding_artifact_ref(result: ChangeAnalysisWorkflowResult) -> str:
    return next(
        (
            finding.artifact_ref
            for finding in result.checkpoint.findings
            if finding.artifact_ref
        ),
        "",
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
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS,
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS_UNIT,
        ProjectWorkflowTaskKind.CHANGE_SYNTHESIS,
    }
    run_id = getattr(task.input, "run_id", None)
    if task.kind not in analysis_kinds or not isinstance(run_id, str):
        return
    run = create_run_store().get(run_id)
    if run is None or run.status == "failed":
        return
    failed = run.model_copy(
        update={
            "status": "failed",
            "findings": [
                *[finding for finding in run.findings if finding.check != "workflow"],
                ValidationFinding(severity="error", check="workflow", message=message),
            ],
        }
    )
    store = create_run_store()
    store.save(failed)
    store.record_run_event(
        run_id,
        "failed",
        message,
        "workflow",
    )
