from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from guidesync_agent.schemas import (
    ModelRole,
    ProviderConfig,
    ProviderKind,
    ProviderRunMetadata,
    ValidationFinding,
)
from guidesync_agent.services.code_change_subagent_constants import (
    CODE_CHANGE_ANALYZER_PROMPT_VERSION,
)
from guidesync_agent.services.model_usage import (
    build_model_call_ledger_entry,
    record_model_call_ledger_entry,
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
    provider_kind = provider_kind_or_none(context.provider)
    if provider_kind is None:
        return None
    try:
        safe_metadata = sanitized_model_metadata(context.metadata)
        metadata = ProviderRunMetadata(
            provider=provider_kind.value,
            model=context.model,
            started_at=context.started_at,
            completed_at=context.completed_at,
            latency_ms=int_metadata(safe_metadata, "latency_ms") or 0,
            token_usage=safe_metadata,
        )
        entry = build_model_call_ledger_entry(
            run_id=context.run_id,
            project_id=context.project_id,
            role=ModelRole.CODE_CHANGE_ANALYSIS,
            config=ProviderConfig(
                provider=provider_kind,
                model=context.model,
                metadata=safe_metadata,
            ),
            metadata=metadata,
            call_id=code_change_call_id(context),
            workflow_task_id=context.workflow_task_id,
            prompt_version=CODE_CHANGE_ANALYZER_PROMPT_VERSION,
            structured_output_schema="CodeChangeAnalysis",
        )
        host_hash = string_metadata(safe_metadata, "base_url_host_hash")
        if host_hash:
            entry = entry.model_copy(update={"base_url_host_hash": host_hash})
        record_model_call_ledger_entry(entry)
    except Exception as exc:  # noqa: BLE001 - workflow should surface ledger failures
        return ValidationFinding(
            severity="warning",
            check="model-usage-ledger",
            message=f"Code-change model usage ledger write failed: {exc}",
            evidence_refs=[f"file:{context.repository_id}:{context.path}"],
        )
    return None


def provider_kind_or_none(value: str) -> ProviderKind | None:
    try:
        return ProviderKind(value)
    except ValueError:
        return None


def code_change_call_id(context: CodeChangeModelUsageContext) -> str:
    digest = hashlib.sha256(
        f"{context.repository_id}\0{context.path}".encode()
    ).hexdigest()[:12]
    prefix = context.run_id or context.project_id
    return f"{prefix}-{ModelRole.CODE_CHANGE_ANALYSIS.value}-{digest}"


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
