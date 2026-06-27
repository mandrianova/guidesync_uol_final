from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from guidesync_agent.schemas import (
    ModelRole,
    ProviderConfig,
    ProviderKind,
    ProviderRunMetadata,
)
from guidesync_agent.services.model_usage import (
    build_model_call_ledger_entry,
    endpoint_host_hash,
    record_model_call_ledger_entry,
    sanitized_model_metadata,
)

EMBEDDING_RANKER_PROMPT_VERSION = "embedding-ranker-v1"


@dataclass(frozen=True)
class EmbeddingModelUsageContext:
    model: str
    base_url: str
    input_count: int
    input_chars: int
    started_at: datetime
    completed_at: datetime
    latency_ms: int
    usage: dict[str, Any]
    project_id: str | None = None
    run_id: str | None = None
    workflow_task_id: str | None = None
    source_id: str | None = None


def record_embedding_model_usage(
    context: EmbeddingModelUsageContext,
) -> str | None:
    metadata = sanitized_model_metadata(
        {
            **context.usage,
            "model_role": ModelRole.EMBEDDING_RANKER.value,
            "endpoint_type": "openai_compatible_embeddings",
            "base_url_host_hash": endpoint_host_hash(context.base_url),
            "embedding_input_tokens": context.usage.get("prompt_tokens"),
            "prompt_input_chars": context.input_chars,
            "embedding_input_count": context.input_count,
        }
    )
    try:
        provider_metadata = ProviderRunMetadata(
            provider=ProviderKind.LOCAL_HTTP.value,
            model=context.model,
            started_at=context.started_at,
            completed_at=context.completed_at,
            latency_ms=context.latency_ms,
            token_usage=metadata,
        )
        entry = build_model_call_ledger_entry(
            run_id=context.run_id,
            project_id=context.project_id,
            role=ModelRole.EMBEDDING_RANKER,
            config=ProviderConfig(
                provider=ProviderKind.LOCAL_HTTP,
                model=context.model,
                metadata=metadata,
            ),
            metadata=provider_metadata,
            call_id=embedding_call_id(context),
            workflow_task_id=context.workflow_task_id,
            prompt_version=EMBEDDING_RANKER_PROMPT_VERSION,
            structured_output_schema="EmbeddingResponse",
        )
        host_hash = metadata.get("base_url_host_hash")
        if isinstance(host_hash, str) and host_hash:
            entry = entry.model_copy(update={"base_url_host_hash": host_hash})
        record_model_call_ledger_entry(entry)
    except Exception as exc:  # noqa: BLE001 - annotation should not fail on ledger issues
        return f"Embedding model usage ledger write failed: {exc}"
    return None


def embedding_call_id(context: EmbeddingModelUsageContext) -> str:
    prefix = context.run_id or context.project_id or "embedding"
    digest = hashlib.sha256(
        f"{context.model}\0{context.source_id or ''}\0{context.started_at.isoformat()}".encode()
    ).hexdigest()[:12]
    return f"{prefix}-{ModelRole.EMBEDDING_RANKER.value}-{digest}"
