from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection

from guidesync_agent.models import (
    report_runs_table,
    run_artifacts_table,
)
from guidesync_agent.schemas import (
    Audience,
    GuideSyncRunResult,
    RunSummary,
)

from .serialization_models import effective_model_configuration_from_provider_config

LEGACY_RUN_AUDIENCE_VALUES = {
    "documentation reviewer": Audience.DEVELOPERS.value,
    "product users": Audience.END_USERS.value,
    "product_users": Audience.END_USERS.value,
}


def run_result_from_snapshot(snapshot: str | dict[str, object]) -> GuideSyncRunResult:
    payload = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
    return GuideSyncRunResult.model_validate(normalized_legacy_run_snapshot(payload))


def normalized_legacy_run_snapshot(snapshot: object) -> object:
    if not isinstance(snapshot, dict):
        return snapshot
    payload = dict(snapshot)
    request = payload.get("request")
    if not isinstance(request, dict):
        return payload
    request_payload = dict(request)
    audience = request_payload.get("audience")
    if isinstance(audience, str):
        normalized_audience = LEGACY_RUN_AUDIENCE_VALUES.get(audience.strip().lower())
        if normalized_audience is not None:
            request_payload["audience"] = normalized_audience
            payload["request"] = request_payload
    return payload


def run_summary(
    result: GuideSyncRunResult,
    *,
    created_at: datetime,
    updated_at: datetime,
) -> RunSummary:
    provider = result.provider_metadata.provider if result.provider_metadata else None
    model = result.provider_metadata.model if result.provider_metadata else None
    effective_model_configuration = (
        result.request.effective_model_configuration
        or effective_model_configuration_from_provider_config(result.request.provider)
    )
    return RunSummary(
        run_id=result.run_id,
        status=result.status,
        title=result.request.report.title,
        created_at=created_at,
        updated_at=updated_at,
        provider=provider,
        model=model,
        effective_model_configuration=effective_model_configuration,
        artifacts=result.artifacts,
    )

def upsert_report_run(
    connection: Connection,
    result: GuideSyncRunResult,
    now: datetime,
    created_at: datetime,
) -> None:
    provider = (
        result.provider_metadata.provider
        if result.provider_metadata
        else result.request.provider.provider
    )
    model = (
        result.provider_metadata.model
        if result.provider_metadata
        else result.request.provider.model
    )
    started_at = result.provider_metadata.started_at if result.provider_metadata else None
    completed_at = result.provider_metadata.completed_at if result.provider_metadata else None
    error_message = next(
        (finding.message for finding in result.findings if finding.severity == "error"),
        None,
    )
    filters = {
        "repositories": [
            {
                "name": repository.name,
                "url": repository.url,
                "ref": repository.ref,
                "since": repository.since,
                "until": repository.until,
                "branches": repository.branches,
                "paths": repository.paths,
            }
            for repository in result.request.repositories
        ]
    }
    effective_model_configuration = (
        result.request.effective_model_configuration
        or effective_model_configuration_from_provider_config(result.request.provider)
    )
    existing = connection.execute(
        select(report_runs_table.c.id).where(report_runs_table.c.id == result.run_id)
    ).one_or_none()
    values = {
        "id": result.run_id,
        "project_id": project_id_from_run_id(result.run_id),
        "status": result.status,
        "mode": None,
        "goal": result.request.goal,
        "audience": result.request.audience.value,
        "model_profile_id": effective_model_configuration.model_profile_id,
        "provider": provider.value if hasattr(provider, "value") else provider,
        "model": model,
        "task_interface_url": result.request.task_interface_url,
        "screenshot_policy": result.request.screenshot_policy.value,
        "requested_model_settings": (
            result.request.requested_model_settings.model_dump(mode="json")
            if result.request.requested_model_settings
            else None
        ),
        "effective_model_configuration": effective_model_configuration.model_dump(mode="json"),
        "project_profile_snapshot_id": result.request.project_profile_snapshot_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "updated_at": now,
        "error_message": error_message,
        "request_snapshot": result.request.model_dump(mode="json"),
        "result_snapshot": result.model_dump(mode="json"),
        "filters": filters,
    }
    if existing is None:
        connection.execute(insert(report_runs_table).values(created_at=created_at, **values))
        return
    connection.execute(
        update(report_runs_table).where(report_runs_table.c.id == result.run_id).values(**values)
    )

def replace_run_artifacts(
    connection: Connection,
    result: GuideSyncRunResult,
    now: datetime,
) -> None:
    connection.execute(
        delete(run_artifacts_table).where(run_artifacts_table.c.run_id == result.run_id)
    )
    for filename, uri in result.artifacts.items():
        connection.execute(
            insert(run_artifacts_table).values(
                id=f"artifact-{uuid4().hex[:12]}",
                run_id=result.run_id,
                artifact_type=filename,
                uri=uri,
                content_type=content_type_for_artifact(filename),
                created_at=now,
            )
        )

def project_id_from_run_id(run_id: str) -> str | None:
    if not run_id.startswith("project-"):
        return None
    parts = run_id.split("-")
    if len(parts) < 3:
        return None
    return "-".join(parts[:2])

def content_type_for_artifact(filename: str) -> str | None:
    if filename.endswith(".html"):
        return "text/html; charset=utf-8"
    if filename.endswith(".md"):
        return "text/markdown; charset=utf-8"
    if filename.endswith(".json"):
        return "application/json; charset=utf-8"
    return None
