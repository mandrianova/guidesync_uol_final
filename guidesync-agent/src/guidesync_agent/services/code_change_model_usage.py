from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from guidesync_agent.schemas import (
    ModelRole,
    ValidationFinding,
)
from guidesync_agent.services.code_change_subagent_constants import (
    CODE_CHANGE_ANALYZER_PROMPT_VERSION,
)
from guidesync_agent.services.model_usage import (
    ModelCallRecordRequest,
    metadata_int,
    provider_kind_or_none,
    record_model_call,
    sanitized_model_metadata,
)


@dataclass(frozen=True)
class CodeChangeModelUsageContext:
    project_id: str
    run_id: str | None
    workflow_task_id: str | None
    repository_id: str
    path: str
    provider: str
    model: str
    metadata: dict[str, Any]
    started_at: datetime
    completed_at: datetime


def record_code_change_model_usage(
    context: CodeChangeModelUsageContext,
) -> ValidationFinding | None:
    provider = provider_kind_or_none(context.provider)
    if provider is None:
        return None
    try:
        safe_metadata = sanitized_model_metadata(context.metadata)
        record_model_call(
            ModelCallRecordRequest(
                project_id=context.project_id,
                run_id=context.run_id,
                workflow_task_id=context.workflow_task_id,
                role=ModelRole.CODE_CHANGE_ANALYSIS,
                provider=provider,
                model=context.model,
                started_at=context.started_at,
                completed_at=context.completed_at,
                latency_ms=metadata_int(safe_metadata, "latency_ms"),
                metadata=safe_metadata,
                call_id=code_change_call_id(context),
                prompt_version=CODE_CHANGE_ANALYZER_PROMPT_VERSION,
                structured_output_schema="CodeChangeAnalysis",
            )
        )
    except Exception as exc:  # noqa: BLE001 - workflow should surface ledger failures
        return ValidationFinding(
            severity="warning",
            check="model-usage-ledger",
            message=f"Code-change model usage ledger write failed: {exc}",
            evidence_refs=[f"file:{context.repository_id}:{context.path}"],
        )
    return None


def code_change_call_id(context: CodeChangeModelUsageContext) -> str:
    digest = hashlib.sha256(
        f"{context.repository_id}\0{context.path}".encode()
    ).hexdigest()[:12]
    prefix = context.run_id or context.project_id
    return f"{prefix}-{ModelRole.CODE_CHANGE_ANALYSIS.value}-{digest}"
