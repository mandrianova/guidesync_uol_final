from __future__ import annotations

import hashlib
from dataclasses import dataclass

from guidesync_agent.agent_runtime.model_usage import (
    ModelCallRecordRequest,
    metadata_datetime,
    metadata_int,
    metadata_string,
    provider_kind_or_none,
    record_model_call,
    sanitized_model_metadata,
)
from guidesync_agent.schemas import (
    ModelRole,
    ScreenshotValidationAttempt,
    ValidationFinding,
)

SCREENSHOT_VISION_PROMPT_VERSION = "screenshot-vision-ocr-v1"


@dataclass(frozen=True)
class ScreenshotModelUsageContext:
    project_id: str | None
    run_id: str
    workflow_task_id: str | None
    scenario: str
    url: str
    image_path: str | None
    attempt: ScreenshotValidationAttempt


def record_screenshot_model_usage(
    context: ScreenshotModelUsageContext,
) -> ValidationFinding | None:
    if context.attempt.model_role is not ModelRole.SCREENSHOT_VISION:
        return None
    metadata = sanitized_model_metadata(context.attempt.model_metadata)
    if not metadata.get("model_call_attempted"):
        return None
    provider = provider_kind_or_none(context.attempt.provider)
    if provider is None or context.attempt.model is None:
        return None
    try:
        record_model_call(
            ModelCallRecordRequest(
                project_id=context.project_id,
                run_id=context.run_id,
                workflow_task_id=context.workflow_task_id,
                role=ModelRole.SCREENSHOT_VISION,
                provider=provider,
                model=context.attempt.model,
                started_at=metadata_datetime(metadata, "started_at"),
                completed_at=metadata_datetime(metadata, "completed_at"),
                latency_ms=metadata_int(metadata, "latency_ms"),
                metadata=metadata,
                error=metadata_string(metadata, "error"),
                call_id=screenshot_call_id(context),
                prompt_version=SCREENSHOT_VISION_PROMPT_VERSION,
                structured_output_schema="ScreenshotVisionModelOutput",
            )
        )
    except Exception as exc:  # noqa: BLE001 - screenshot validation should surface ledger failures
        return ValidationFinding(
            severity="warning",
            check="model-usage-ledger",
            message=f"Screenshot vision model usage ledger write failed: {exc}",
            evidence_refs=[f"screenshot:{context.scenario}:{context.url}"],
        )
    return None


def screenshot_call_id(context: ScreenshotModelUsageContext) -> str:
    image_key = context.image_path or context.url
    digest = hashlib.sha256(
        f"{context.scenario}\0{context.url}\0{image_key}\0{context.attempt.attempt}".encode()
    ).hexdigest()[:12]
    return f"{context.run_id}-{ModelRole.SCREENSHOT_VISION.value}-{digest}"
