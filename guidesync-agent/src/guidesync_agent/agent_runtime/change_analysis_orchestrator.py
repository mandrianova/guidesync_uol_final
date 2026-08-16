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
    ChangeAnalysisWorkflowResult,
    ModelRole,
    ReleaseChangeConfidence,
    ReleaseChangeFinding,
    ReleaseChangeKind,
)
from guidesync_agent.services.change_analysis.checkpoint import (
    covered_keys,
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
ORCHESTRATOR_PROMPT_VERSION = "docs-update-change-analysis-orchestrator-v4"
MAX_CHECKPOINT_SUMMARY_CHARS = 2_000
ORCHESTRATOR_PASS_LIMIT = 48
ORCHESTRATOR_PASS_ITEM_LIMIT = 20
ORCHESTRATOR_TOTAL_TIMEOUT_SECONDS = 3_600
ORCHESTRATOR_TOTAL_OUTPUT_TOKENS_LIMIT = 64_000


def run_change_analysis_orchestrator(
    deps: ChangeAnalysisOrchestratorDeps,
) -> ChangeAnalysisWorkflowResult:
    if deterministic_analysis_enabled():
        save_deterministic_finding(deps)
        return completed_result(deps)

    if not uncovered_inventory(deps.inventory, deps.checkpoint) and deps.checkpoint.findings:
        return completed_result(deps)
    previous_covered = len(covered_keys(deps.checkpoint))
    first_pass = len(deps.checkpoint.transcript_ids) + 1
    for pass_number in range(first_pass, first_pass + ORCHESTRATOR_PASS_LIMIT):
        deps.active_inventory_keys = [
            item.key
            for item in uncovered_inventory(deps.inventory, deps.checkpoint)[
                :ORCHESTRATOR_PASS_ITEM_LIMIT
            ]
        ]
        output, transcript_id = run_orchestrator_pass(deps, pass_number)
        if transcript_id and transcript_id not in deps.checkpoint.transcript_ids:
            deps.checkpoint.transcript_ids.append(transcript_id)
        deps.checkpoint.summary = output.strip()[:MAX_CHECKPOINT_SUMMARY_CHARS]
        persist_checkpoint(deps)
        if not deps.checkpoint.findings:
            raise RuntimeError(
                "Change-analysis orchestrator returned without saving an analysis artifact."
            )
        remaining = uncovered_inventory(deps.inventory, deps.checkpoint)
        if not remaining:
            return completed_result(deps)
        covered_total = len(covered_keys(deps.checkpoint))
        if covered_total <= previous_covered:
            raise RuntimeError(
                "Change-analysis orchestrator returned without new durable inventory "
                f"coverage; {len(remaining)} inventory item(s) remain."
            )
        previous_covered = covered_total
    remaining = uncovered_inventory(deps.inventory, deps.checkpoint)
    raise RuntimeError(
        "Change-analysis orchestrator reached its bounded pass limit before durable "
        f"coverage was complete: {len(remaining)} inventory item(s) remain."
    )


def run_orchestrator_pass(
    deps: ChangeAnalysisOrchestratorDeps,
    pass_number: int,
) -> tuple[str, str | None]:
    prompt = load_prompt_file(
        ORCHESTRATOR_PROMPT_PATH,
        version=ORCHESTRATOR_PROMPT_VERSION,
    )
    config = provider_config_for_role(ModelRole.CODE_CHANGE_ANALYSIS)
    config = config.model_copy(
        update={
            "execution_limits": config.execution_limits.model_copy(
                update={
                    "total_timeout_seconds": max(
                        config.execution_limits.total_timeout_seconds,
                        ORCHESTRATOR_TOTAL_TIMEOUT_SECONDS,
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
                output_model=None,
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
                total_output_tokens_limit=ORCHESTRATOR_TOTAL_OUTPUT_TOKENS_LIMIT,
            )
        )
        if not isinstance(runtime_result.output, str):
            raise TypeError("Change-analysis orchestrator returned a non-text final response.")
        return runtime_result.output, runtime_result.transcript_id
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
        "current_pass_items": len(deps.active_inventory_keys),
        "current_pass_item_limit": ORCHESTRATOR_PASS_ITEM_LIMIT,
        "findings_total": len(deps.checkpoint.findings),
        "checkpoint_summary": checkpoint_summary,
    }
    return (
        "Resume semantic change analysis from the durable checkpoint below. The payload "
        "intentionally omits raw inventory and finding bodies. Read them with the paginated "
        "tools, starting with `list_change_inventory`. This model session receives one "
        "bounded pass of final-diff paths; commit metadata is optional context. Persist "
        "every analysis artifact with `save_change_artifact`. Finish the current session "
        "when `list_change_inventory(uncovered_only=true)` reports `total: 0`; the runtime "
        "will start the next pass if workflow items remain. Never claim that an item was "
        "processed unless that tool confirmed it.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
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
    path_items = [item for item in deps.inventory.items if item.path]
    evidence_refs = [f"inventory:{key}" for key in keys[:20]]
    replace_finding(
        deps.checkpoint,
        ReleaseChangeFinding(
            id="deterministic-repository-change",
            title=("Repository changes" if keys else "No selected changes"),
            kind=ReleaseChangeKind.INTERNAL,
            technical_summary=(
                f"The selected range changes {len(path_items)} repository path(s)."
                if keys
                else "The selected range contains no inventory items."
            ),
            user_impact=(
                "Detailed user impact requires model-backed semantic analysis."
                if keys
                else "No user-visible change was found in the selected range."
            ),
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
                structured_output_schema=None,
                error=str(error) if error else None,
            )
        )
    except Exception:  # noqa: BLE001 - ledger failure must not discard durable findings
        return
