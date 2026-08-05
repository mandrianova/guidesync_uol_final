from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from guidesync_agent.agent_runtime.model_usage import (
    ModelCallLedgerRequest,
    build_model_call_ledger_entry,
    record_model_call_ledger_entry,
)
from guidesync_agent.agent_runtime.token_budget import evaluate_token_budgets
from guidesync_agent.agent_runtime.transcript_types import LLMTranscriptContext
from guidesync_agent.agent_runtime.transcripts import record_llm_transcript_from_metadata
from guidesync_agent.evidence import collect_evidence
from guidesync_agent.llm.providers import model_role_metadata, provider_for
from guidesync_agent.reports import write_reports
from guidesync_agent.schemas import (
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ModelRole,
    ProjectProfileContextEvidence,
    ProjectProfileSnapshot,
    ProjectProfileStatus,
    ProviderRunMetadata,
    ValidationFinding,
)
from guidesync_agent.services.model_configuration import (
    rehydrate_global_provider,
    with_run_provider_settings,
)
from guidesync_agent.services.screenshots import (
    ScreenshotWorkflowContext,
    capture_task_screenshots,
)
from guidesync_agent.services.validation import ValidationService
from guidesync_agent.storage import create_run_store
from guidesync_agent.workflows.documentation_update import (
    DocumentationUpdateWorkflowContext,
    apply_documentation_edit_to_update,
    attach_retrieved_docs_to_update,
    prepare_documentation_update_workflow,
)

logger = logging.getLogger(__name__)


def save_run_state(
    request: GuideSyncRunRequest,
    status: str,
    findings: list[ValidationFinding] | None = None,
) -> GuideSyncRunResult:
    result = GuideSyncRunResult(
        run_id=request.run_id,
        status=status,
        request=request,
        evidence=EvidenceBundle(),
        findings=findings or [],
    )
    store = create_run_store()
    store.save(result)
    store.record_run_event(result.run_id, status, f"Run state changed to {status}.")
    return result


async def run_guidesync(
    request: GuideSyncRunRequest,
    *,
    workflow_task_id: str | None = None,
) -> GuideSyncRunResult:
    validation_service = ValidationService()
    request.provider = with_run_provider_settings(
        rehydrate_global_provider(request.provider),
        request,
    )
    request.provider = request.provider.model_copy(
        update={
            "metadata": {
                **request.provider.metadata,
                "project_id": run_project_id(request),
                "run_id": request.run_id,
                "workflow_task_id": workflow_task_id,
            }
        }
    )
    store = create_run_store()
    store.record_run_event(
        request.run_id,
        "running",
        "Syncing repositories and collecting evidence.",
        "collect",
    )
    logger.info("Run %s collecting repository evidence.", request.run_id)
    evidence = collect_evidence(request.repositories, request.documentation)
    logger.info(
        "Run %s collected evidence: %s commits, %s docs, %s warnings.",
        request.run_id,
        len(evidence.commits),
        len(evidence.documentation),
        len(evidence.warnings),
    )
    store.save(
        GuideSyncRunResult(
            run_id=request.run_id,
            status="running",
            request=request,
            evidence=evidence,
            findings=[],
        )
    )
    workflow_context = prepare_documentation_update_workflow(
        request,
        workflow_task_id=workflow_task_id,
    )
    if (
        workflow_context.project_profile is not None
        and workflow_context.project_profile.status == ProjectProfileStatus.COMPLETED
    ):
        evidence.project_profile = project_profile_context_evidence(
            workflow_context.project_profile
        )
    screenshot_context = capture_task_screenshots(
        ScreenshotWorkflowContext(
            request=request,
            evidence=evidence,
            file_summaries=workflow_context.file_summaries,
            output_dir=request.report.output_dir / "screenshots",
            workflow_task_id=workflow_task_id,
        )
    )
    workflow_context.artifacts.update(screenshot_context.artifacts)
    workflow_context.findings.extend(screenshot_context.findings)
    provider = provider_for(request.provider)
    update = None
    metadata = None
    status = "completed"
    findings = []
    try:
        provider_started = datetime.now(UTC)
        provider_start = time.perf_counter()
        store.record_run_event(
            request.run_id, "running", "Generating release notes.", "agent"
        )
        logger.info(
            "Run %s calling provider %s model %s.",
            request.run_id,
            request.provider.provider.value,
            request.provider.model,
        )
        update, metadata = await provider.generate_update(
            goal=request.goal,
            audience=request.audience,
            evidence=evidence,
            config=request.provider,
        )
        metadata.token_usage = {
            **metadata.token_usage,
            "orchestrator_subordinate_artifact_refs": subordinate_artifact_refs(
                workflow_context
            ),
        }
        attach_retrieved_docs_to_update(update, workflow_context.retrieved_docs)
        apply_documentation_edit_to_update(request, update, workflow_context)
        logger.info("Run %s provider call completed.", request.run_id)
    except Exception as exc:  # noqa: BLE001 - result should preserve provider failure
        logger.exception("Run %s provider call failed.", request.run_id)
        status = "failed"
        if metadata is None:
            completed = datetime.now(UTC)
            metadata = ProviderRunMetadata(
                provider=request.provider.provider.value,
                model=request.provider.model,
                started_at=provider_started,
                completed_at=completed,
                latency_ms=int((time.perf_counter() - provider_start) * 1000),
                token_usage=model_role_metadata(request.provider),
                error=str(exc),
            )
        findings.append(ValidationFinding(severity="error", check="provider", message=str(exc)))
    usage_finding = record_orchestrator_model_usage(
        request,
        metadata,
        workflow_task_id=workflow_task_id,
    )
    if usage_finding is not None:
        findings.append(usage_finding)
    transcript_finding = record_orchestrator_transcript(
        request,
        metadata,
        workflow_task_id=workflow_task_id,
    )
    if transcript_finding is not None:
        findings.append(transcript_finding)
    findings.extend(token_budget_findings(request.run_id, workflow_task_id))
    all_findings = [
        *workflow_context.findings,
        *findings,
        *validation_service.after_release_notes(update, evidence),
    ]
    status = validation_service.final_status(status, all_findings)
    result = GuideSyncRunResult(
        run_id=request.run_id,
        status=status,
        request=request,
        evidence=evidence,
        update=update,
        provider_metadata=metadata,
        findings=all_findings,
    )
    result.artifacts = dict(workflow_context.artifacts)
    result.artifacts = write_reports(result)
    store.save(result)
    store.record_run_event(result.run_id, status, f"Run finished with status {status}.", "complete")
    return result


def project_profile_context_evidence(
    profile: ProjectProfileSnapshot,
) -> ProjectProfileContextEvidence:
    taxonomy = profile.taxonomy
    return ProjectProfileContextEvidence(
        id=profile.id,
        version=profile.version,
        prompt_version=profile.prompt_version,
        summary=profile.summary,
        project_description=profile.project_description,
        project_structure=profile.project_structure,
        architecture=profile.architecture,
        core_concepts=profile.core_concepts,
        agent_context=profile.agent_context,
        taxonomy_version=taxonomy.version,
        categories=taxonomy.categories,
    )


def subordinate_artifact_refs(
    context: DocumentationUpdateWorkflowContext,
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for summary in context.file_summaries:
        if summary.artifact_uri:
            refs.append(
                {
                    "role": "code_change_analysis",
                    "path": summary.path,
                    "artifact_ref": summary.artifact_uri,
                }
            )
    artifact_roles = {
        "project-profile.json": "project_profile_file_reader",
        "retrieved-docs.json": "knowledge_retrieval",
        "screenshot-results.json": "screenshot_vision",
    }
    for name, artifact_ref in sorted(context.artifacts.items()):
        role = artifact_roles.get(name)
        if role is None:
            continue
        refs.append({"role": role, "artifact_ref": artifact_ref})
    return refs


def record_orchestrator_model_usage(
    request: GuideSyncRunRequest,
    metadata: ProviderRunMetadata | None,
    *,
    workflow_task_id: str | None = None,
) -> ValidationFinding | None:
    if metadata is None:
        return None
    try:
        record_model_call_ledger_entry(
            build_model_call_ledger_entry(
                ModelCallLedgerRequest(
                    run_id=request.run_id,
                    project_id=run_project_id(request),
                    role=ModelRole.ORCHESTRATOR,
                    workflow_task_id=workflow_task_id,
                    structured_output_schema="DocumentationUpdateModelOutput",
                ),
                config=request.provider,
                metadata=metadata,
            )
        )
    except Exception as exc:  # noqa: BLE001 - run result should expose ledger failures
        logger.exception("Run %s failed to record model usage.", request.run_id)
        return ValidationFinding(
            severity="warning",
            check="model-usage-ledger",
            message=f"Model usage ledger write failed: {exc}",
        )
    return None


def record_orchestrator_transcript(
    request: GuideSyncRunRequest,
    metadata: ProviderRunMetadata | None,
    *,
    workflow_task_id: str | None = None,
) -> ValidationFinding | None:
    if metadata is None:
        return None
    try:
        record_llm_transcript_from_metadata(
            LLMTranscriptContext(
                project_id=run_project_id(request),
                run_id=request.run_id,
                workflow_task_id=workflow_task_id,
                model_role=ModelRole.ORCHESTRATOR,
                provider=request.provider.provider,
                model=metadata.model or request.provider.model,
                metadata=metadata.token_usage,
                started_at=metadata.started_at,
                model_call_id=f"{request.run_id}-{ModelRole.ORCHESTRATOR.value}",
                token_ledger_entry_id=(
                    f"{request.run_id}-{ModelRole.ORCHESTRATOR.value}"
                ),
                endpoint_type=request.provider.metadata.get("endpoint_type"),
            ),
            completed_at=metadata.completed_at,
            error=metadata.error,
        )
    except Exception as exc:  # noqa: BLE001 - run result should expose transcript failures
        logger.exception("Run %s failed to record LLM transcript.", request.run_id)
        return ValidationFinding(
            severity="warning",
            check="llm-transcript",
            message=f"LLM transcript write failed: {exc}",
        )
    return None


def token_budget_findings(
    run_id: str,
    workflow_task_id: str | None,
) -> list[ValidationFinding]:
    try:
        return evaluate_token_budgets(run_id, workflow_task_id=workflow_task_id)
    except Exception as exc:  # noqa: BLE001 - run should expose budget evaluation issues
        logger.exception("Run %s failed to evaluate token budget.", run_id)
        return [
            ValidationFinding(
                severity="warning",
                check="token-budget",
                message=f"Token budget evaluation failed: {exc}",
            )
        ]


def run_project_id(request: GuideSyncRunRequest) -> str | None:
    for repository in request.repositories:
        if repository.project_id:
            return repository.project_id
    return None
