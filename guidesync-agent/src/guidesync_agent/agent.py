from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from guidesync_agent.app_logging import configure_logging
from guidesync_agent.evidence import collect_evidence
from guidesync_agent.providers import provider_for
from guidesync_agent.reports import write_reports
from guidesync_agent.schemas import (
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
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
    request.provider = rehydrate_global_provider(request.provider)
    store = create_run_store()
    store.record_run_event(request.run_id, "running", "Collecting repository evidence.", "collect")
    evidence = collect_evidence(request.repositories, request.documentation)
    provider = provider_for(request.provider)
    update = None
    metadata = None
    status = "completed"
    findings = []
    try:
        store.record_run_event(
            request.run_id, "running", "Generating documentation update.", "agent"
        )
        update, metadata = await provider.generate_update(
            goal=request.goal,
            audience=request.audience,
            evidence=evidence,
            config=request.provider,
        )
    except Exception as exc:  # noqa: BLE001 - result should preserve provider failure
        status = "failed"
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


def rehydrate_global_provider(config):
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


def load_request(path: Path) -> GuideSyncRunRequest:
    return GuideSyncRunRequest.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Run a GuideSync documentation-maintenance task.")
    parser.add_argument("request", type=Path, help="Path to a GuideSync run request JSON file.")
    args = parser.parse_args()
    result = asyncio.run(run_guidesync(load_request(args.request)))
    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
