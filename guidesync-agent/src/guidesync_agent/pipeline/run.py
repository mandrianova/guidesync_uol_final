from __future__ import annotations

import time
from datetime import UTC, datetime

from guidesync_agent.evidence import collect_evidence
from guidesync_agent.llm.providers import provider_for
from guidesync_agent.reports import write_reports
from guidesync_agent.schemas import (
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProviderConfig,
    ProviderRunMetadata,
    ValidationFinding,
)
from guidesync_agent.storage import (
    GLOBAL_MODEL_PROFILE_ID,
    create_model_settings_store,
    create_run_store,
)
from guidesync_agent.validation import validate_update


def save_run_state(
    request: GuideSyncRunRequest,
    status: str,
    findings: list[ValidationFinding] | None = None,
) -> GuideSyncRunResult:
    result = GuideSyncRunResult(
        run_id=request.run_id,
        status=status,
        request=request,
        evidence=EvidenceBundle(),
        findings=findings or [],
    )
    store = create_run_store()
    store.save(result)
    store.record_run_event(result.run_id, status, f"Run state changed to {status}.")
    return result


async def run_guidesync(request: GuideSyncRunRequest) -> GuideSyncRunResult:
    request.provider = with_run_provider_metadata(
        rehydrate_global_provider(request.provider),
        request,
    )
    store = create_run_store()
    store.record_run_event(
        request.run_id,
        "running",
        "Syncing repositories and collecting evidence.",
        "collect",
    )
    evidence = collect_evidence(request.repositories, request.documentation)
    provider = provider_for(request.provider)
    update = None
    metadata = None
    status = "completed"
    findings = []
    try:
        provider_started = datetime.now(UTC)
        provider_start = time.perf_counter()
        store.record_run_event(
            request.run_id, "running", "Generating release notes.", "agent"
        )
        update, metadata = await provider.generate_update(
            goal=request.goal,
            audience=request.audience,
            evidence=evidence,
            config=request.provider,
        )
    except Exception as exc:  # noqa: BLE001 - result should preserve provider failure
        status = "failed"
        if metadata is None:
            completed = datetime.now(UTC)
            metadata = ProviderRunMetadata(
                provider=request.provider.provider.value,
                model=request.provider.model,
                started_at=provider_started,
                completed_at=completed,
                latency_ms=int((time.perf_counter() - provider_start) * 1000),
                error=str(exc),
            )
        findings.append(ValidationFinding(severity="error", check="provider", message=str(exc)))
    result = GuideSyncRunResult(
        run_id=request.run_id,
        status=status,
        request=request,
        evidence=evidence,
        update=update,
        provider_metadata=metadata,
        findings=[*findings, *validate_update(update, evidence)],
    )
    result.artifacts = write_reports(result)
    store.save(result)
    store.record_run_event(result.run_id, status, f"Run finished with status {status}.", "complete")
    return result


def rehydrate_global_provider(config: ProviderConfig) -> ProviderConfig:
    if config.metadata.get("model_profile_id") != GLOBAL_MODEL_PROFILE_ID:
        return config
    stored = create_model_settings_store().provider_config()
    return stored.model_copy(
        update={
            "provider": config.provider,
            "model": config.model,
            "base_url": config.base_url,
            "timeout_seconds": config.timeout_seconds,
            "metadata": config.metadata,
        }
    )


def with_run_provider_metadata(
    config: ProviderConfig,
    request: GuideSyncRunRequest,
) -> ProviderConfig:
    metadata = {
        **config.metadata,
        "screenshot_dir": str(request.report.output_dir / "screenshots"),
    }
    return config.model_copy(update={"metadata": metadata})
