from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from guidesync_agent.agent_runtime.model_usage import (
    ModelCallRecordRequest,
    record_model_call,
)
from guidesync_agent.agent_runtime.pydantic_ai import (
    PydanticAgentRunRequest,
    PydanticAgentRuntimeResult,
    run_pydantic_agent_sync,
)
from guidesync_agent.prompts.loader import load_prompt_file
from guidesync_agent.schemas import (
    ChangeAnalysisCoverage,
    ChangeAnalysisCoverageDisposition,
    ChangeAnalysisOrchestratorOutput,
    ChangeAnalysisWorkflowResult,
    ModelRole,
    ReleaseChangeConfidence,
    ReleaseChangeFinding,
    ReleaseChangeKind,
)
from guidesync_agent.services.change_analysis_checkpoint import (
    covered_keys,
    replace_coverage,
    replace_finding,
    uncovered_inventory,
)
from guidesync_agent.services.model_roles import provider_config_for_role
from guidesync_agent.settings import get_settings
from guidesync_agent.tools.change_analysis_orchestrator import (
    ChangeAnalysisOrchestratorDeps,
    persist_checkpoint,
    register_change_analysis_orchestrator_tools,
)

ORCHESTRATOR_PROMPT_PATH = "docs_update/change_analysis_orchestrator.md"
ORCHESTRATOR_PROMPT_VERSION = "docs-update-change-analysis-orchestrator-v1"
MAX_CHECKPOINT_SUMMARY_CHARS = 2_000
ORCHESTRATOR_REQUEST_LIMIT = 128
ORCHESTRATOR_TOOL_CALLS_LIMIT = 512
ORCHESTRATOR_OUTPUT_RETRIES = 8


def run_change_analysis_orchestrator(
    deps: ChangeAnalysisOrchestratorDeps,
) -> ChangeAnalysisWorkflowResult:
    if deterministic_analysis_enabled():
        save_deterministic_finding(deps)
        return completed_result(deps)

    if not uncovered_inventory(deps.inventory, deps.checkpoint):
        return completed_result(deps)
    previous_covered = len(covered_keys(deps.checkpoint))
    output, transcript_id = run_orchestrator_pass(deps, 1)
    if transcript_id and transcript_id not in deps.checkpoint.transcript_ids:
        deps.checkpoint.transcript_ids.append(transcript_id)
    deps.checkpoint.summary = output.checkpoint_summary.strip()
    save_unresolved_coverage(deps, output.unresolved_keys)
    persist_checkpoint(deps)
    covered_total = len(covered_keys(deps.checkpoint))
    if covered_total == previous_covered:
        raise RuntimeError(
            "Change-analysis orchestrator made no durable coverage progress."
        )
    remaining = uncovered_inventory(deps.inventory, deps.checkpoint)
    if remaining:
        raise RuntimeError(
            "Change-analysis orchestrator returned before durable coverage was complete: "
            f"{len(remaining)} inventory item(s) remain."
        )
    return completed_result(deps)


def run_orchestrator_pass(
    deps: ChangeAnalysisOrchestratorDeps,
    pass_number: int,
) -> tuple[ChangeAnalysisOrchestratorOutput, str | None]:
    deps.coverage_at_pass_start = len(covered_keys(deps.checkpoint))
    prompt = load_prompt_file(
        ORCHESTRATOR_PROMPT_PATH,
        version=ORCHESTRATOR_PROMPT_VERSION,
    )
    config = provider_config_for_role(ModelRole.CODE_CHANGE_ANALYSIS)
    config = config.model_copy(
        update={
            "execution_limits": config.execution_limits.model_copy(
                update={
                    "request_limit": max(
                        config.execution_limits.request_limit,
                        ORCHESTRATOR_REQUEST_LIMIT,
                    ),
                    "tool_calls_limit": max(
                        config.execution_limits.tool_calls_limit,
                        ORCHESTRATOR_TOOL_CALLS_LIMIT,
                    ),
                }
            )
        }
    )
    call_id = f"{deps.run_id}-{ModelRole.CODE_CHANGE_ANALYSIS.value}-orchestrator-{pass_number}"
    user_prompt = orchestrator_user_prompt(deps, pass_number)
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    runtime_result: PydanticAgentRuntimeResult | None = None
    error: Exception | None = None
    try:
        runtime_result = run_pydantic_agent_sync(
            PydanticAgentRunRequest(
                prompt=user_prompt,
                instructions=prompt.content,
                output_model=ChangeAnalysisOrchestratorOutput,
                deps=deps,
                deps_type=ChangeAnalysisOrchestratorDeps,
                config=config,
                model_role=ModelRole.CODE_CHANGE_ANALYSIS,
                project_id=deps.project_id,
                run_id=deps.run_id,
                workflow_task_id=deps.workflow_task_id,
                model_call_id=call_id,
                token_ledger_entry_id=call_id,
                prompt_metadata=prompt.usage_metadata("change_analysis_orchestrator"),
                register_tools=register_change_analysis_orchestrator_tools,
                retries=ORCHESTRATOR_OUTPUT_RETRIES,
                requires_tools=False,
                allow_early_output=False,
            )
        )
        return (
            ChangeAnalysisOrchestratorOutput.model_validate(runtime_result.output),
            runtime_result.transcript_id,
        )
    except Exception as exc:
        error = exc
        raise
    finally:
        completed_at = datetime.now(UTC)
        record_orchestrator_model_call(
            deps,
            config.provider.value,
            config.model,
            config.base_url,
            call_id,
            prompt,
            user_prompt,
            runtime_result,
            error,
            started_at,
            completed_at,
            int((time.perf_counter() - started) * 1000),
        )


def orchestrator_user_prompt(
    deps: ChangeAnalysisOrchestratorDeps,
    pass_number: int,
) -> str:
    remaining = uncovered_inventory(deps.inventory, deps.checkpoint)
    checkpoint_summary = deps.checkpoint.summary.strip()
    if len(checkpoint_summary) > MAX_CHECKPOINT_SUMMARY_CHARS:
        checkpoint_summary = (
            checkpoint_summary[:MAX_CHECKPOINT_SUMMARY_CHARS]
            + "\n[checkpoint summary truncated]"
        )
    payload = {
        "run_id": deps.run_id,
        "pass": pass_number,
        "inventory_total": len(deps.inventory.items),
        "covered_total": len(covered_keys(deps.checkpoint)),
        "remaining_total": len(remaining),
        "findings_total": len(deps.checkpoint.findings),
        "checkpoint_summary": checkpoint_summary,
    }
    return (
        "Resume semantic change analysis from the durable checkpoint below. The payload "
        "intentionally omits raw inventory and finding bodies. Read them with the paginated "
        "tools, starting with `list_change_inventory`. Persist every accepted finding or "
        "no-release-note decision before returning final output. Never claim that an item "
        "was processed unless a persistence tool confirmed it.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def save_unresolved_coverage(
    deps: ChangeAnalysisOrchestratorDeps,
    unresolved_keys: list[str],
) -> None:
    known = {item.key for item in deps.inventory.items}
    for key in dict.fromkeys(unresolved_keys):
        if key not in known or key in covered_keys(deps.checkpoint):
            continue
        replace_coverage(
            deps.checkpoint,
            ChangeAnalysisCoverage(
                key=key,
                disposition=ChangeAnalysisCoverageDisposition.UNRESOLVED,
                reason="The orchestrator requires more evidence for this inventory item.",
            ),
        )


def completed_result(deps: ChangeAnalysisOrchestratorDeps) -> ChangeAnalysisWorkflowResult:
    deps.checkpoint.completed = True
    persist_checkpoint(deps)
    return ChangeAnalysisWorkflowResult(
        inventory=deps.inventory,
        checkpoint=deps.checkpoint,
    )


def deterministic_analysis_enabled() -> bool:
    configured = get_settings().models.code_change.provider or "pydantic_ai"
    return configured in {"deterministic", "fake", "fixture"}


def save_deterministic_finding(deps: ChangeAnalysisOrchestratorDeps) -> None:
    keys = [item.key for item in deps.inventory.items]
    if not keys:
        deps.checkpoint.completed = True
        persist_checkpoint(deps)
        return
    path_items = [item for item in deps.inventory.items if item.path]
    evidence_refs = [f"inventory:{key}" for key in keys[:20]]
    replace_finding(
        deps.checkpoint,
        ReleaseChangeFinding(
            id="deterministic-repository-change",
            title="Repository changes",
            kind=ReleaseChangeKind.INTERNAL,
            technical_summary=(
                f"The selected range changes {len(path_items)} repository path(s)."
            ),
            user_impact="Detailed user impact requires model-backed semantic analysis.",
            coverage_keys=keys,
            evidence_refs=evidence_refs,
            release_note_eligible=False,
            confidence=ReleaseChangeConfidence.LOW,
        ),
    )
    persist_checkpoint(deps)


def record_orchestrator_model_call(  # noqa: PLR0913 - ledger boundary
    deps: ChangeAnalysisOrchestratorDeps,
    provider: str,
    model: str,
    base_url: str | None,
    call_id: str,
    prompt: object,
    user_prompt: str,
    runtime_result: PydanticAgentRuntimeResult | None,
    error: Exception | None,
    started_at: datetime,
    completed_at: datetime,
    latency_ms: int,
) -> None:
    usage = dict(runtime_result.usage) if runtime_result is not None else {}
    usage.update(
        {
            "prompt_input_chars": len(user_prompt),
            "tool_call_count": deps.tool_calls,
            "model_turn_count": usage.get("requests", 1),
        }
    )
    try:
        record_model_call(
            ModelCallRecordRequest(
                project_id=deps.project_id,
                run_id=deps.run_id,
                workflow_task_id=deps.workflow_task_id,
                role=ModelRole.CODE_CHANGE_ANALYSIS,
                provider=provider,
                model=model,
                started_at=started_at,
                completed_at=completed_at,
                latency_ms=latency_ms,
                metadata=usage,
                call_id=call_id,
                base_url=base_url,
                prompt_version=getattr(prompt, "version", ORCHESTRATOR_PROMPT_VERSION),
                structured_output_schema=ChangeAnalysisOrchestratorOutput.__name__,
                error=str(error) if error else None,
            )
        )
    except Exception:  # noqa: BLE001 - ledger failure must not discard durable findings
        return
