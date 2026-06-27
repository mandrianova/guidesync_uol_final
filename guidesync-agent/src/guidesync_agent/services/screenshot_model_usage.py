from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from guidesync_agent.schemas import (
    ModelRole,
    ProviderConfig,
    ProviderKind,
    ProviderRunMetadata,
    ScreenshotValidationAttempt,
    ValidationFinding,
)
from guidesync_agent.services.model_usage import (
    build_model_call_ledger_entry,
    record_model_call_ledger_entry,
    sanitized_model_metadata,
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
    provider_kind = provider_kind_or_none(context.attempt.provider or "")
    if provider_kind is None or context.attempt.model is None:
        return None
    try:
        provider_metadata = ProviderRunMetadata(
            provider=provider_kind.value,
            model=context.attempt.model,
            started_at=datetime_metadata(metadata, "started_at"),
            completed_at=datetime_metadata(metadata, "completed_at"),
            latency_ms=int_metadata(metadata, "latency_ms"),
            token_usage=metadata,
            error=string_metadata(metadata, "error"),
        )
        entry = build_model_call_ledger_entry(
            run_id=context.run_id,
            project_id=context.project_id,
            role=ModelRole.SCREENSHOT_VISION,
            config=ProviderConfig(
                provider=provider_kind,
                model=context.attempt.model,
                metadata=metadata,
            ),
            metadata=provider_metadata,
            call_id=screenshot_call_id(context),
            workflow_task_id=context.workflow_task_id,
            prompt_version=SCREENSHOT_VISION_PROMPT_VERSION,
            structured_output_schema="ScreenshotVisionModelOutput",
        )
        host_hash = string_metadata(metadata, "base_url_host_hash")
        if host_hash:
            entry = entry.model_copy(update={"base_url_host_hash": host_hash})
        record_model_call_ledger_entry(entry)
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


def provider_kind_or_none(value: str) -> ProviderKind | None:
    try:
        return ProviderKind(value)
    except ValueError:
        return None


def datetime_metadata(metadata: Mapping[str, Any], key: str) -> datetime:
    value = metadata.get(key)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(UTC)


def string_metadata(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def int_metadata(metadata: Mapping[str, Any], key: str) -> int:
    value = metadata.get(key)
    if value in (None, ""):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed >= 0 else 0
