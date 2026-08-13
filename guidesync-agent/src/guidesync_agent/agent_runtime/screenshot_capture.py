from __future__ import annotations

import time
from datetime import UTC, datetime

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
)
from guidesync_agent.services.model_configuration import (
    rehydrate_global_provider,
    with_run_provider_settings,
)
from guidesync_agent.tools.browser import register_browser_agent_tools
from guidesync_agent.tools.evidence import EvidenceAgentDeps


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
        rehydrate_global_provider(run.request.provider),
        run.request,
    )
    config = config.model_copy(
        update={
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
                register_tools=register_browser_agent_tools,
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
