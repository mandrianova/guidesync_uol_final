from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from guidesync_agent.agent_runtime.release_notes import ReleaseNotesGenerationInput
from guidesync_agent.llm.providers import provider_for
from guidesync_agent.pipeline.run import record_knowledge_access_manifest
from guidesync_agent.reports import read_artifact, write_reports
from guidesync_agent.schemas import (
    AnalysisArtifactManifest,
    DocumentationEditPlan,
    DocumentationUpdate,
    GuideSyncRunResult,
    KnowledgeSearchResult,
    ProviderRunMetadata,
    RunContextSources,
    ScreenshotPolicy,
    ValidationFinding,
)
from guidesync_agent.services.reports.publication import build_publication_report
from guidesync_agent.storage import create_run_store
from guidesync_agent.tools.knowledge_evidence import select_knowledge_evidence
from guidesync_agent.workflows.documentation_update import (
    DocumentationUpdateWorkflowContext,
    write_workflow_artifact,
)


@dataclass(frozen=True)
class PilotCondition:
    id: str
    knowledge_base: bool


@dataclass(frozen=True)
class PilotSource:
    run: GuideSyncRunResult
    analysis_manifest: AnalysisArtifactManifest
    retrieved_docs: list[KnowledgeSearchResult]
    edit_plan: DocumentationEditPlan | None
    condition_timeout_seconds: int


CONDITIONS = (
    PilotCondition(id="G-SYN", knowledge_base=True),
    PilotCondition(id="G-K-SYN", knowledge_base=False),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a bounded paired synthesis pilot from one completed real-project run. "
            "This does not rerun upstream change analysis and must not be reported as a "
            "full end-to-end G/G-K effectiveness experiment."
        )
    )
    parser.add_argument("source_run_id")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--condition-timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--condition",
        action="append",
        choices=[condition.id for condition in CONDITIONS],
        dest="conditions",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if args.condition_timeout_seconds < 1:
        raise ValueError("condition timeout must be at least 1 second")
    store = create_run_store()
    source = store.get(args.source_run_id)
    if source is None or source.status != "completed":
        raise ValueError("source run must exist and be completed")
    analysis_manifest = load_analysis_manifest(source)
    retrieved_docs = load_retrieved_docs(source)
    edit_plan = load_edit_plan(source)
    pilot_source = PilotSource(
        run=source,
        analysis_manifest=analysis_manifest,
        retrieved_docs=retrieved_docs,
        edit_plan=edit_plan,
        condition_timeout_seconds=args.condition_timeout_seconds,
    )
    completed: list[GuideSyncRunResult] = []
    conditions = [
        condition
        for condition in CONDITIONS
        if not args.conditions or condition.id in args.conditions
    ]
    for repetition in range(1, args.repetitions + 1):
        for condition in conditions:
            completed.append(
                await run_condition(
                    pilot_source,
                    condition,
                    repetition,
                )
            )
    print(
        json.dumps(
            {
                "source_run_id": source.run_id,
                "runs": [
                    {
                        "run_id": run.run_id,
                        "status": run.status,
                        "condition": condition_from_run_id(run.run_id),
                        "artifacts": run.artifacts,
                    }
                    for run in completed
                ],
            },
            indent=2,
        )
    )


async def run_condition(
    pilot_source: PilotSource,
    condition: PilotCondition,
    repetition: int,
) -> GuideSyncRunResult:
    source = pilot_source.run
    run_id = (
        f"{source.run_id.rsplit('-', 1)[0]}-causal-{condition.id.lower()}-"
        f"r{repetition}-{uuid4().hex[:6]}"
    )
    output_dir = Path("outputs") / run_id
    metadata = {
        **source.request.provider.metadata,
        "project_id": source.request.repositories[0].project_id,
        "run_id": run_id,
        "workflow_task_id": f"pilot-{condition.id.lower()}-r{repetition}",
        "evaluation_condition_id": condition.id,
        "evaluation_repetition": repetition,
    }
    provider_config = source.request.provider.model_copy(
        update={"metadata": metadata}
    )
    request = source.request.model_copy(
        update={
            "run_id": run_id,
            "provider": provider_config,
            "task_interface_url": None,
            "screenshot_policy": ScreenshotPolicy.DISABLED,
            "context_sources": RunContextSources(
                project_profile=True,
                knowledge_base=condition.knowledge_base,
                edit_planning=True,
            ),
            "report": source.request.report.model_copy(
                update={"output_dir": output_dir}
            ),
            "evaluation_notes": (
                f"Bounded downstream synthesis pilot {condition.id}, repetition "
                f"{repetition}, using frozen artifacts from {source.run_id}. Upstream "
                "change analysis was not rerun, so quality is not_evaluated and this run "
                "is not a full G/G-K causal result."
            ),
        }
    )
    selected_docs = pilot_source.retrieved_docs if condition.knowledge_base else []
    context = DocumentationUpdateWorkflowContext(
        retrieved_docs=selected_docs,
        edit_plan=pilot_source.edit_plan,
    )
    pending = GuideSyncRunResult(
        run_id=run_id,
        status="running",
        request=request,
        evidence=source.evidence,
    )
    store = create_run_store()
    store.save(pending)
    started = datetime.now(UTC)
    try:
        async with asyncio.timeout(pilot_source.condition_timeout_seconds):
            update, provider_metadata = await provider_for(provider_config).generate_update(
                generation_input=source_generation_input(
                    source,
                    pilot_source.analysis_manifest,
                    selected_docs,
                    pilot_source.edit_plan,
                    condition,
                ),
                config=provider_config,
            )
        record_knowledge_access_manifest(
            request,
            context,
            update,
            provider_metadata,
        )
        context.artifacts["pilot-scorecard.json"] = write_workflow_artifact(
            output_dir / "workflow" / "pilot-scorecard.json",
            pilot_scorecard(
                source.run_id,
                condition,
                repetition,
                update,
                provider_metadata,
            ),
        )
        result = GuideSyncRunResult(
            run_id=run_id,
            status="completed",
            request=request,
            evidence=source.evidence,
            update=update,
            provider_metadata=provider_metadata,
            artifacts=context.artifacts,
        )
    except Exception as exc:  # noqa: BLE001 - failed pilot runs are retained
        context.artifacts["pilot-scorecard.json"] = write_workflow_artifact(
            output_dir / "workflow" / "pilot-scorecard.json",
            failed_pilot_scorecard(
                source.run_id,
                condition,
                repetition,
                exc,
                started,
            ),
        )
        result = GuideSyncRunResult(
            run_id=run_id,
            status="failed",
            request=request,
            evidence=source.evidence,
            artifacts=context.artifacts,
            findings=[
                ValidationFinding(
                    severity="error",
                    check="profile-knowledge-synthesis-pilot",
                    message=f"{type(exc).__name__}: {exc}",
                )
            ],
        )
    artifacts = write_reports(result)
    completed = result.model_copy(update={"artifacts": artifacts})
    store.save(completed, build_publication_report(completed))
    store.record_run_event(
        run_id,
        completed.status,
        (
            f"Bounded synthesis pilot {condition.id} finished after "
            f"{int((datetime.now(UTC) - started).total_seconds())} seconds."
        ),
        "evaluation",
    )
    return completed


def source_generation_input(
    source: GuideSyncRunResult,
    analysis_manifest: AnalysisArtifactManifest,
    retrieved_docs: list[KnowledgeSearchResult],
    edit_plan: DocumentationEditPlan | None,
    condition: PilotCondition,
) -> ReleaseNotesGenerationInput:
    request = source.request
    return ReleaseNotesGenerationInput(
        goal=request.goal,
        audience=request.audience.value,
        evidence=source.evidence,
        analysis_manifest=analysis_manifest,
        edit_plan=edit_plan,
        product_name=request.report.product_name,
        locale=request.report.locale.value,
        screenshot_policy=ScreenshotPolicy.DISABLED,
        selected_knowledge=select_knowledge_evidence(retrieved_docs),
        knowledge_context_enabled=condition.knowledge_base,
    )


def load_analysis_manifest(source: GuideSyncRunResult) -> AnalysisArtifactManifest:
    payload = json.loads(read_artifact(source.artifacts["analysis-manifest.json"]).body)
    return AnalysisArtifactManifest.model_validate(payload)


def load_retrieved_docs(source: GuideSyncRunResult) -> list[KnowledgeSearchResult]:
    payload = json.loads(read_artifact(source.artifacts["retrieved-docs.json"]).body)
    return [KnowledgeSearchResult.model_validate(item) for item in payload["results"]]


def load_edit_plan(source: GuideSyncRunResult) -> DocumentationEditPlan | None:
    artifact_ref = source.artifacts.get("documentation-edit-plan.json")
    if artifact_ref is None:
        return None
    return DocumentationEditPlan.model_validate(
        json.loads(read_artifact(artifact_ref).body)
    )


def pilot_scorecard(
    source_run_id: str,
    condition: PilotCondition,
    repetition: int,
    update: DocumentationUpdate,
    metadata: ProviderRunMetadata,
) -> dict[str, object]:
    usage = metadata.token_usage
    cited_refs = {
        ref
        for ref in [
            *(item.source for item in update.evidence_used),
            *(ref for change in update.changes for ref in change.evidence_refs),
        ]
        if ref.startswith("knowledge:")
    }
    return {
        "source_run_id": source_run_id,
        "condition_id": condition.id,
        "repetition": repetition,
        "scope": "downstream_synthesis_only",
        "operational_status": "completed",
        "quality_measurement_status": "not_evaluated",
        "quality_reason": (
            "The reused analysis manifest may contain upstream knowledge effects and the "
            "output has not been independently blinded or adjudicated."
        ),
        "raw_counts": {
            "reported_changes": len(update.changes),
            "selected_knowledge": len(usage.get("knowledge_context_selected", [])),
            "read_knowledge": len(usage.get("knowledge_context_read_refs", [])),
            "cited_knowledge": len(cited_refs),
        },
        "usage": {
            key: usage.get(key)
            for key in (
                "requests",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "release_notes_generation_attempts",
                "release_notes_provider_failure_attempts",
                "release_notes_correction_attempts",
            )
        },
        "runtime": {
            "provider": metadata.provider,
            "model": metadata.model,
            "latency_ms": metadata.latency_ms,
            "error": metadata.error,
        },
    }


def failed_pilot_scorecard(
    source_run_id: str,
    condition: PilotCondition,
    repetition: int,
    error: Exception,
    started: datetime,
) -> dict[str, object]:
    return {
        "source_run_id": source_run_id,
        "condition_id": condition.id,
        "repetition": repetition,
        "scope": "downstream_synthesis_only",
        "operational_status": "failed",
        "quality_measurement_status": "not_evaluated",
        "quality_reason": "Generation did not produce an accepted output.",
        "raw_counts": None,
        "runtime": {
            "latency_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
            "error_type": type(error).__name__,
            "error": str(error),
        },
    }


def condition_from_run_id(run_id: str) -> str:
    return "G-K-SYN" if "g-k-syn" in run_id else "G-SYN"


if __name__ == "__main__":
    asyncio.run(main())
