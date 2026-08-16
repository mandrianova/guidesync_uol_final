from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from pydantic_ai import ModelRetry, RunContext

from guidesync_agent.agent_runtime.concurrency import agent_concurrency_key
from guidesync_agent.agent_runtime.model_usage import (
    ModelCallRecordRequest,
    record_model_call,
)
from guidesync_agent.agent_runtime.pydantic_ai import (
    PydanticAgentRunRequest,
    run_pydantic_agent,
)
from guidesync_agent.prompts.screenshot_capture import (
    build_screenshot_capture_task_prompt,
    screenshot_capture_prompt,
)
from guidesync_agent.schemas import (
    GuideSyncRunResult,
    ModelRole,
    ScreenshotPolicy,
    ScreenshotRetryDisposition,
)
from guidesync_agent.services.model_configuration import (
    rehydrate_provider_credentials,
    with_run_provider_settings,
)
from guidesync_agent.tools.browser import register_browser_agent_tools
from guidesync_agent.tools.evidence import EvidenceAgentDeps
from guidesync_agent.tools.screenshot_images import register_screenshot_image_tools

SCREENSHOT_CAPTURE_TOTAL_TIMEOUT_SECONDS = 1_800
SCREENSHOT_CAPTURE_MAX_VALIDATION_ATTEMPTS = 3


def register_screenshot_capture_agent_tools(agent: Any) -> None:
    register_browser_agent_tools(agent)
    register_screenshot_image_tools(agent)

    @agent.output_validator
    def require_changed_validation_retry(
        ctx: RunContext[EvidenceAgentDeps],
        output: str,
    ) -> str:
        pending_edits = pending_screenshot_edit_feedback(ctx.deps)
        if pending_edits is not None:
            raise ModelRetry(pending_edits)
        feedback = screenshot_validation_retry_feedback(ctx.deps)
        if feedback is not None:
            raise ModelRetry(feedback)
        return output


def pending_screenshot_edit_feedback(deps: EvidenceAgentDeps) -> str | None:
    pending = [
        capture.capture_id
        for capture in deps.evidence.browser_screenshots
        if capture.capture_id in deps.screenshot_session_capture_ids
        and capture.derivative_path
        and not capture.edit_finalized
    ]
    if not pending:
        return None
    return (
        "Edited screenshot derivatives are still awaiting publication review. Call "
        "view_screenshot with variant=derivative when visual inspection is needed, then "
        "call finalize_screenshot_edits for: "
        + ", ".join(capture_id for capture_id in pending if capture_id)
    )


def screenshot_validation_retry_feedback(deps: EvidenceAgentDeps) -> str | None:
    pending: list[str] = []
    for change_id in dict.fromkeys(deps.screenshot_candidate_change_ids):
        attempts = deps.screenshot_validation_attempts.get(change_id, [])
        if not attempts:
            continue
        latest = attempts[-1]
        if (
            latest.retry_disposition is not ScreenshotRetryDisposition.RETRY_CAPTURE
            or len(attempts) >= SCREENSHOT_CAPTURE_MAX_VALIDATION_ATTEMPTS
        ):
            continue
        details = [f"reasons={', '.join(latest.reasons) or 'unspecified'}"]
        if latest.missing_text:
            details.append(f"missing_text={', '.join(latest.missing_text)}")
        if latest.semantic_mismatches:
            details.append(
                f"semantic_mismatches={'; '.join(latest.semantic_mismatches)}"
            )
        if latest.ui_state or latest.page_summary:
            details.append(f"observed_state={latest.ui_state or latest.page_summary}")
        pending.append(f"- change_id={change_id}; " + "; ".join(details))
    if not pending:
        return None
    return "\n".join(
        [
            "A retryable screenshot validation failed. Before finishing, inspect the "
            "diagnostics and make a material correction for each listed change. You may inspect "
            "and edit the current image, then finalize it, or make another capture with a "
            "different grounded route, action sequence, viewport, capture target, or expected "
            "visible text. Do not repeat an unchanged attempt.",
            *pending,
        ]
    )


async def run_screenshot_capture_agent(
    run: GuideSyncRunResult,
    *,
    project_id: str,
    workflow_task_id: str,
) -> tuple[str, str | None]:
    if not (run.request.task_interface_url or "").strip():
        raise ValueError("Screenshot capture requires a task interface URL.")
    if run.update is None or not run.update.screenshot_requests:
        raise ValueError("Screenshot capture requires at least one planned request.")

    config = with_run_provider_settings(
        rehydrate_provider_credentials(run.request.provider),
        run.request,
    )
    config = config.model_copy(
        update={
            "execution_limits": config.execution_limits.model_copy(
                update={
                    "total_timeout_seconds": max(
                        config.execution_limits.total_timeout_seconds,
                        SCREENSHOT_CAPTURE_TOTAL_TIMEOUT_SECONDS,
                    ),
                }
            ),
            "metadata": {
                **config.metadata,
                "project_id": project_id,
                "run_id": run.run_id,
                "workflow_task_id": workflow_task_id,
                "agent_purpose": "screenshot_capture",
            }
        }
    )
    browser = config.browser
    if browser is None:
        raise ValueError("Screenshot capture requires browser settings.")
    deps = EvidenceAgentDeps(
        evidence=run.evidence,
        browser=browser,
        report_locale=run.request.report.locale.value,
        screenshot_policy=ScreenshotPolicy.OPTIONAL,
        screenshot_candidate_change_ids=[
            item.change_id for item in run.update.screenshot_requests
        ],
        screenshot_candidate_evidence_refs={
            item.change_id: item.evidence_refs for item in run.update.screenshot_requests
        },
        project_id=project_id,
        run_id=run.run_id,
        workflow_task_id=workflow_task_id,
        held_model_concurrency_key=agent_concurrency_key(config),
    )
    prompt_file = screenshot_capture_prompt()
    prompt = build_screenshot_capture_task_prompt(run)
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    runtime_result = None
    error: Exception | None = None
    call_id = f"{run.run_id}-screenshot-capture-{workflow_task_id}"
    try:
        runtime_result = await run_pydantic_agent(
            PydanticAgentRunRequest(
                prompt=prompt,
                instructions=prompt_file.content,
                output_model=None,
                deps=deps,
                deps_type=EvidenceAgentDeps,
                config=config,
                model_role=ModelRole.ORCHESTRATOR,
                project_id=project_id,
                run_id=run.run_id,
                workflow_task_id=workflow_task_id,
                model_call_id=call_id,
                token_ledger_entry_id=call_id,
                prompt_metadata=prompt_file.usage_metadata("screenshot_capture"),
                register_tools=register_screenshot_capture_agent_tools,
                requires_tools=True,
            )
        )
        if not isinstance(runtime_result.output, str):
            raise TypeError("Screenshot capture agent returned a non-text response.")
        return runtime_result.output, runtime_result.transcript_id
    except Exception as exc:
        error = exc
        raise
    finally:
        completed_at = datetime.now(UTC)
        record_model_call(
            ModelCallRecordRequest(
                project_id=project_id,
                run_id=run.run_id,
                workflow_task_id=workflow_task_id,
                role=ModelRole.ORCHESTRATOR,
                provider=config.provider,
                model=config.model,
                base_url=config.base_url,
                call_id=call_id,
                prompt_version=prompt_file.version,
                started_at=started_at,
                completed_at=completed_at,
                latency_ms=int((time.perf_counter() - started) * 1000),
                metadata=(runtime_result.usage if runtime_result is not None else {}),
                error=str(error) if error is not None else None,
            )
        )
