from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from guidesync_agent.evidence import collect_evidence
from guidesync_agent.providers import provider_for
from guidesync_agent.reports import write_reports
from guidesync_agent.schemas import GuideSyncRunRequest, GuideSyncRunResult, ValidationFinding
from guidesync_agent.storage import FileRunStore
from guidesync_agent.validation import validate_update


async def run_guidesync(request: GuideSyncRunRequest) -> GuideSyncRunResult:
    evidence = collect_evidence(request.repositories, request.documentation)
    provider = provider_for(request.provider)
    update = None
    metadata = None
    status = "completed"
    findings = []
    try:
        update, metadata = await provider.generate_update(
            goal=request.goal,
            audience=request.audience,
            evidence=evidence,
            config=request.provider,
        )
    except Exception as exc:  # noqa: BLE001 - result should preserve provider failure
        status = "failed"
        findings.append(
            ValidationFinding(severity="error", check="provider", message=str(exc))
        )
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
    FileRunStore().save(result)
    return result


def load_request(path: Path) -> GuideSyncRunRequest:
    return GuideSyncRunRequest.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a GuideSync documentation-maintenance task.")
    parser.add_argument("request", type=Path, help="Path to a GuideSync run request JSON file.")
    args = parser.parse_args()
    result = asyncio.run(run_guidesync(load_request(args.request)))
    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
