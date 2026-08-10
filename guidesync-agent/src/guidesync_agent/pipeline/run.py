from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from guidesync_agent.agent_runtime.model_usage import (
    ModelCallLedgerRequest,
    build_model_call_ledger_entry,
    record_model_call_ledger_entry,
)
from guidesync_agent.agent_runtime.release_notes import ReleaseNotesGenerationInput
from guidesync_agent.agent_runtime.token_budget import evaluate_token_budgets
from guidesync_agent.agent_runtime.transcript_types import LLMTranscriptContext
from guidesync_agent.agent_runtime.transcripts import record_llm_transcript_from_metadata
from guidesync_agent.evidence import collect_evidence
from guidesync_agent.llm.providers import model_role_metadata, provider_for
from guidesync_agent.reports import write_reports
from guidesync_agent.schemas import (
    AnalysisArtifactManifest,
    DocumentationUpdate,
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
from guidesync_agent.services.screenshots import screenshot_evidence_artifacts
from guidesync_agent.services.validation import ValidationService
from guidesync_agent.storage import RunStore, create_run_store
from guidesync_agent.tools.knowledge_evidence import select_knowledge_evidence
from guidesync_agent.workflows.documentation_update import (
    DocumentationUpdateWorkflowContext,
    apply_documentation_edit_to_update,
    prepare_documentation_update_workflow,
    write_workflow_artifact,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerationOutcome:
    update: DocumentationUpdate | None
    metadata: ProviderRunMetadata | None
    status: str
    findings: list[ValidationFinding]


@dataclass(frozen=True)
class RunCompletion:
    outcome: GenerationOutcome
    status: str
    findings: list[ValidationFinding]


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
    workflow_context: DocumentationUpdateWorkflowContext | None = None,
    analysis_manifest: AnalysisArtifactManifest | None = None,
) -> GuideSyncRunResult:
    validation_service = ValidationService()
    configure_run_provider(request, workflow_task_id)
    store = create_run_store()
    evidence = collect_and_persist_evidence(request, store)
    workflow_context = await prepare_run_workflow_context(
        request,
        evidence,
        workflow_context,
        workflow_task_id=workflow_task_id,
    )
    outcome = await generate_release_notes(
        request,
        evidence,
        workflow_context,
        analysis_manifest=analysis_manifest,
        store=store,
    )
    instrumentation_findings = orchestrator_instrumentation_findings(
        request,
        outcome.metadata,
        workflow_task_id=workflow_task_id,
    )
    all_findings = [
        *workflow_context.findings,
        *outcome.findings,
        *instrumentation_findings,
        *validation_service.after_release_notes(outcome.update, evidence),
        *validation_service.after_screenshot_coverage(
            request.screenshot_policy,
            evidence,
            outcome.update,
        ),
    ]
    status = validation_service.final_status(outcome.status, all_findings)
    return persist_completed_run(
        request,
        evidence,
        workflow_context,
        RunCompletion(outcome, status, all_findings),
        store,
    )


def configure_run_provider(
    request: GuideSyncRunRequest,
    workflow_task_id: str | None,
) -> None:
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


def collect_and_persist_evidence(
    request: GuideSyncRunRequest,
    store: RunStore,
) -> EvidenceBundle:
    store.record_run_event(
        request.run_id,
        "running",
        "Syncing repositories and collecting evidence.",
        "collect",
    )
    logger.info("Run %s collecting repository evidence.", request.run_id)
    evidence = collect_evidence(
        request.repositories,
        request.documentation if request.context_sources.knowledge_base else [],
    )
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
    return evidence


async def prepare_run_workflow_context(
    request: GuideSyncRunRequest,
    evidence: EvidenceBundle,
    context: DocumentationUpdateWorkflowContext | None,
    *,
    workflow_task_id: str | None,
) -> DocumentationUpdateWorkflowContext:
    if context is None:
        context = prepare_documentation_update_workflow(
            request,
            evidence=evidence,
            workflow_task_id=workflow_task_id,
        )
    if (
        context.project_profile is not None
        and context.project_profile.status == ProjectProfileStatus.COMPLETED
    ):
        evidence.project_profile = project_profile_context_evidence(context.project_profile)
    return context


async def generate_release_notes(
    request: GuideSyncRunRequest,
    evidence: EvidenceBundle,
    context: DocumentationUpdateWorkflowContext,
    *,
    analysis_manifest: AnalysisArtifactManifest | None,
    store: RunStore,
) -> GenerationOutcome:
    provider = provider_for(request.provider)
    update = None
    metadata = None
    status = "completed"
    findings = []
    try:
        provider_started = datetime.now(UTC)
        provider_start = time.perf_counter()
        store.record_run_event(request.run_id, "running", "Generating release notes.", "agent")
        logger.info(
            "Run %s calling provider %s model %s.",
            request.run_id,
            request.provider.provider.value,
            request.provider.model,
        )
        update, metadata = await provider.generate_update(
            generation_input=ReleaseNotesGenerationInput(
                goal=request.goal,
                audience=request.audience,
                evidence=evidence,
                analysis_manifest=analysis_manifest,
                edit_plan=context.edit_plan,
                product_name=request.report.product_name,
                locale=request.report.locale.value,
                task_interface_url=request.task_interface_url,
                screenshot_policy=request.screenshot_policy,
                screenshot_candidate_change_ids=[
                    summary.id
                    for summary in context.file_summaries
                    if summary.needs_screenshot_check
                ],
                selected_knowledge=(
                    select_knowledge_evidence(context.retrieved_docs)
                    if request.context_sources.knowledge_base
                    else []
                ),
                knowledge_context_enabled=request.context_sources.knowledge_base,
            ),
            config=request.provider,
        )
        record_knowledge_access_manifest(request, context, update, metadata)
        apply_documentation_edit_to_update(request, update, context)
        logger.info("Run %s provider call completed.", request.run_id)
    except Exception as exc:
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
    return GenerationOutcome(update, metadata, status, findings)


def record_knowledge_access_manifest(
    request: GuideSyncRunRequest,
    context: DocumentationUpdateWorkflowContext,
    update: DocumentationUpdate,
    metadata: ProviderRunMetadata,
) -> None:
    selected = select_knowledge_evidence(context.retrieved_docs)
    selected_by_ref = {item.evidence_ref: item for item in selected}
    read_refs = set(metadata.token_usage.get("knowledge_context_read_refs", []))
    cited_refs = {
        reference
        for reference in [
            *(item.source for item in update.evidence_used),
            *(reference for change in update.changes for reference in change.evidence_refs),
        ]
        if reference.startswith("knowledge:")
    }
    planned_path = context.edit_plan.target_path if context.edit_plan else None
    items = [
        {
            "evidence_ref": item.evidence_ref,
            "path": item.path,
            "heading": item.heading,
            "content_hash": item.content_hash,
            "source_commit": item.source_commit,
            "available": request.context_sources.knowledge_base,
            "retrieved": True,
            "selected": True,
            "read_by_model": item.evidence_ref in read_refs,
            "cited": item.evidence_ref in cited_refs,
            "used_for_planning": item.path == planned_path,
            "used_for_generation": (
                item.evidence_ref in read_refs and item.evidence_ref in cited_refs
            ),
        }
        for item in selected
    ]
    inaccessible_citations = sorted(cited_refs.difference(selected_by_ref))
    manifest: dict[str, object] = {
        "knowledge_base_enabled": request.context_sources.knowledge_base,
        "selected_count": len(selected),
        "read_count": len(read_refs),
        "cited_count": len(cited_refs),
        "inaccessible_citations": inaccessible_citations,
        "access_events": metadata.token_usage.get(
            "knowledge_context_access_events", []
        ),
        "items": items,
    }
    checksum = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    context.artifacts["knowledge-access-manifest.json"] = write_workflow_artifact(
        request.report.output_dir / "workflow" / "knowledge-access-manifest.json",
        {**manifest, "checksum": checksum},
    )


def orchestrator_instrumentation_findings(
    request: GuideSyncRunRequest,
    metadata: ProviderRunMetadata | None,
    *,
    workflow_task_id: str | None,
) -> list[ValidationFinding]:
    findings = []
    for finding in (
        record_orchestrator_model_usage(
            request,
            metadata,
            workflow_task_id=workflow_task_id,
        ),
        record_orchestrator_transcript(
            request,
            metadata,
            workflow_task_id=workflow_task_id,
        ),
    ):
        if finding is not None:
            findings.append(finding)
    findings.extend(token_budget_findings(request.run_id, workflow_task_id))
    return findings


def persist_completed_run(
    request: GuideSyncRunRequest,
    evidence: EvidenceBundle,
    context: DocumentationUpdateWorkflowContext,
    completion: RunCompletion,
    store: RunStore,
) -> GuideSyncRunResult:
    outcome = completion.outcome
    result = GuideSyncRunResult(
        run_id=request.run_id,
        status=completion.status,
        request=request,
        evidence=evidence,
        update=outcome.update,
        provider_metadata=outcome.metadata,
        findings=completion.findings,
    )
    result.artifacts = dict(context.artifacts)
    result.artifacts.update(screenshot_evidence_artifacts(request.report.output_dir, evidence))
    result.artifacts = write_reports(result)
    store.save(result)
    store.record_run_event(
        result.run_id,
        completion.status,
        f"Run finished with status {completion.status}.",
        "complete",
    )
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
    except Exception as exc:
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
                token_ledger_entry_id=(f"{request.run_id}-{ModelRole.ORCHESTRATOR.value}"),
                endpoint_type=request.provider.metadata.get("endpoint_type"),
            ),
            completed_at=metadata.completed_at,
            error=metadata.error,
        )
    except Exception as exc:
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
    except Exception as exc:
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
