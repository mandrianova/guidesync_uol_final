from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection
from typing import cast

import pytest
from pydantic import ValidationError
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Table,
    Text,
    event,
    insert,
    select,
)
from sqlalchemy.engine import Connection
from storage_test_utils import sqlite_database_url

from guidesync_agent.config import ArtifactStorageConfig
from guidesync_agent.models import (
    evaluation_experiments_table,
    knowledge_index_runs_table,
    llm_conversation_events_table,
    llm_conversations_table,
    model_call_ledger_table,
    project_workflow_tasks_table,
    projects_table,
    report_runs_table,
    run_artifacts_table,
    run_events_table,
)
from guidesync_agent.schemas.project_cleanup import ProjectCleanupResource, ProjectCleanupState
from guidesync_agent.schemas.run_cleanup import RunCleanupRequest
from guidesync_agent.services.project_cleanup import ProjectCleanupPlanError
from guidesync_agent.services.run_cleanup import RunCleanupService
from guidesync_agent.storage.database_run_cleanup import DatabaseRunCleanupStore

PROJECT_ID = "project-run-cleanup"
TARGET_RUN_ID = "legacy-run"
PROTECTED_RUN_ID = "evidence-run"


class FakeS3Client:
    def __init__(self, keys: set[str]) -> None:
        self.keys = keys

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
        prefix = str(kwargs["Prefix"])
        return {
            "Contents": [{"Key": key} for key in sorted(self.keys) if key.startswith(prefix)],
            "IsTruncated": False,
        }

    def delete_objects(self, **kwargs: object) -> dict[str, object]:
        request = kwargs["Delete"]
        assert isinstance(request, dict)
        objects = cast(dict[str, object], request)["Objects"]
        assert isinstance(objects, list)
        for item in objects:
            assert isinstance(item, dict)
            self.keys.discard(str(cast(dict[str, object], item)["Key"]))
        return {}


def test_cleanup_preview_apply_and_repeat_preserve_project_state(tmp_path: Path) -> None:
    store = cleanup_store(tmp_path)
    seed_run_graph(store)
    s3 = FakeS3Client(
        {
            f"reports/{TARGET_RUN_ID}/run.json",
            f"reports/{TARGET_RUN_ID}/unregistered-debug.json",
            f"reports/{PROTECTED_RUN_ID}/run.json",
        }
    )
    service = cleanup_service(store, s3)
    request = RunCleanupRequest(
        target_run_ids=[TARGET_RUN_ID],
        protected_run_ids=[PROTECTED_RUN_ID],
    )

    plan = service.preview(request)

    counts = {item.resource: item.count for item in plan.runs[0].resource_counts}
    assert plan.safe_to_apply is True
    assert plan.runs[0].s3_keys == [
        f"reports/{TARGET_RUN_ID}/run.json",
        f"reports/{TARGET_RUN_ID}/unregistered-debug.json",
    ]
    assert counts[ProjectCleanupResource.REPORT_RUNS] == 1
    assert counts[ProjectCleanupResource.RUN_EVENTS] == 1
    assert counts[ProjectCleanupResource.RUN_ARTIFACTS] == 1
    assert counts[ProjectCleanupResource.WORKFLOW_TASKS] == 1
    assert counts[ProjectCleanupResource.LLM_CONVERSATIONS] == 1
    assert counts[ProjectCleanupResource.LLM_CONVERSATION_EVENTS] == 1
    assert counts[ProjectCleanupResource.MODEL_CALL_LEDGER] == 1

    result = service.apply(plan, plan.checksum)

    assert result.complete is True
    assert result.deleted_run_ids == [TARGET_RUN_ID]
    assert result.already_absent_run_ids == []
    assert s3.keys == {f"reports/{PROTECTED_RUN_ID}/run.json"}
    assert store.preview_run(TARGET_RUN_ID).state is ProjectCleanupState.ALREADY_ABSENT
    assert store.preview_run(PROTECTED_RUN_ID).state is ProjectCleanupState.PRESENT
    assert project_data_exists(store)

    repeated_plan = service.preview(request)
    repeated = service.apply(repeated_plan, repeated_plan.checksum)
    assert repeated.deleted_run_ids == []
    assert repeated.already_absent_run_ids == [TARGET_RUN_ID]
    assert repeated.complete is True


@pytest.mark.parametrize(
    ("publication_snapshot", "workflow_status", "evaluation_manifest", "expected"),
    [
        ({"schema_version": "1.0"}, "completed", {}, "publication"),
        (None, "running", {}, "workflow"),
        (None, "completed", {"source_run_id": TARGET_RUN_ID}, "evaluation"),
    ],
)
def test_cleanup_refuses_protected_or_active_run_data(
    tmp_path: Path,
    publication_snapshot: dict[str, object] | None,
    workflow_status: str,
    evaluation_manifest: dict[str, object],
    expected: str,
) -> None:
    store = cleanup_store(tmp_path)
    seed_run_graph(
        store,
        publication_snapshot=publication_snapshot,
        workflow_status=workflow_status,
        evaluation_manifest=evaluation_manifest,
    )
    service = cleanup_service(store, FakeS3Client(set()))

    plan = service.preview(
        RunCleanupRequest(
            target_run_ids=[TARGET_RUN_ID],
            protected_run_ids=[PROTECTED_RUN_ID],
        )
    )

    assert plan.safe_to_apply is False
    if expected == "publication":
        assert plan.runs[0].publication_available is True
    elif expected == "workflow":
        assert plan.runs[0].active_workflow_task_ids
    else:
        assert plan.runs[0].evaluation_reference_ids
    with pytest.raises(ProjectCleanupPlanError, match="protected or active"):
        service.apply(plan, plan.checksum)
    assert store.preview_run(TARGET_RUN_ID).state is ProjectCleanupState.PRESENT


def test_cleanup_refuses_stale_plan(tmp_path: Path) -> None:
    store = cleanup_store(tmp_path)
    seed_run_graph(store)
    s3 = FakeS3Client(set())
    service = cleanup_service(store, s3)
    request = RunCleanupRequest(
        target_run_ids=[TARGET_RUN_ID],
        protected_run_ids=[PROTECTED_RUN_ID],
    )
    plan = service.preview(request)
    s3.keys.add(f"reports/{TARGET_RUN_ID}/created-after-preview.json")

    with pytest.raises(ProjectCleanupPlanError, match="stale"):
        service.apply(plan, plan.checksum)


def test_cleanup_requires_a_non_empty_exact_target() -> None:
    with pytest.raises(ValidationError, match="non-empty target run id"):
        RunCleanupRequest(target_run_ids=[" "])


def cleanup_store(tmp_path: Path) -> DatabaseRunCleanupStore:
    store = DatabaseRunCleanupStore(sqlite_database_url(tmp_path / "run-cleanup.db"))

    @event.listens_for(store.engine, "connect")
    def enable_foreign_keys(dbapi_connection: SQLiteConnection, _: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return store


def cleanup_service(store: DatabaseRunCleanupStore, s3: FakeS3Client) -> RunCleanupService:
    return RunCleanupService(
        store,
        ArtifactStorageConfig(
            bucket="guidesync-test-artifacts",
            endpoint_url="http://minio.invalid",
            prefix="reports",
        ),
        s3,
    )


def seed_run_graph(
    store: DatabaseRunCleanupStore,
    *,
    publication_snapshot: dict[str, object] | None = None,
    workflow_status: str = "completed",
    evaluation_manifest: dict[str, object] | None = None,
) -> None:
    now = datetime.now(UTC)
    with store.engine.begin() as connection:
        add_row(connection, projects_table, {"id": PROJECT_ID, "name": "Run cleanup"})
        add_report_run(connection, TARGET_RUN_ID, publication_snapshot)
        add_report_run(connection, PROTECTED_RUN_ID, None)
        add_row(
            connection,
            project_workflow_tasks_table,
            {
                "id": "workflow-target",
                "project_id": PROJECT_ID,
                "status": workflow_status,
                "input": {"run_id": TARGET_RUN_ID},
            },
        )
        add_row(connection, run_events_table, {"run_id": TARGET_RUN_ID})
        add_row(
            connection,
            run_artifacts_table,
            {
                "run_id": TARGET_RUN_ID,
                "artifact_type": "run.json",
                "uri": f"s3://guidesync-test-artifacts/reports/{TARGET_RUN_ID}/run.json",
            },
        )
        add_row(
            connection,
            llm_conversations_table,
            {
                "id": "conversation-target",
                "project_id": PROJECT_ID,
                "run_id": TARGET_RUN_ID,
                "started_at": now,
            },
        )
        add_row(
            connection,
            llm_conversation_events_table,
            {"conversation_id": "conversation-target"},
        )
        add_row(
            connection,
            model_call_ledger_table,
            {"project_id": PROJECT_ID, "run_id": TARGET_RUN_ID, "started_at": now},
        )
        add_row(connection, knowledge_index_runs_table, {"project_id": PROJECT_ID})
        add_row(
            connection,
            evaluation_experiments_table,
            {
                "id": "experiment-preserved",
                "project_id": PROJECT_ID,
                "manifest": evaluation_manifest or {},
            },
        )


def add_report_run(
    connection: Connection,
    run_id: str,
    publication_snapshot: dict[str, object] | None,
) -> None:
    add_row(
        connection,
        report_runs_table,
        {
            "id": run_id,
            "project_id": PROJECT_ID,
            "status": "completed",
            "publication_snapshot": publication_snapshot,
        },
    )


def add_row(
    connection: Connection,
    table: Table,
    overrides: Mapping[str, object],
) -> None:
    values: dict[str, object] = {}
    for column in table.columns:
        if column.name in overrides:
            values[column.name] = overrides[column.name]
        elif column.nullable or column.default is not None:
            continue
        elif column.primary_key:
            values[column.name] = f"{table.name}-{column.name}"
        else:
            values[column.name] = required_value(column.type, column.name)
    connection.execute(insert(table).values(**values))


def required_value(column_type: object, name: str) -> object:
    if isinstance(column_type, (String, Text)):
        return "completed" if name == "status" else f"value-{name}"
    if isinstance(column_type, Boolean):
        return False
    if isinstance(column_type, (Float, Integer)):
        return 1.0 if isinstance(column_type, Float) else 1
    if isinstance(column_type, DateTime):
        return datetime.now(UTC)
    if isinstance(column_type, JSON):
        return {}
    raise TypeError(f"No test value for {column_type!r}")


def project_data_exists(store: DatabaseRunCleanupStore) -> bool:
    with store.engine.begin() as connection:
        project_id = connection.execute(
            select(projects_table.c.id).where(projects_table.c.id == PROJECT_ID)
        ).scalar_one_or_none()
        knowledge_count = connection.execute(
            select(knowledge_index_runs_table.c.project_id).where(
                knowledge_index_runs_table.c.project_id == PROJECT_ID
            )
        ).scalar_one_or_none()
        experiment_id = connection.execute(
            select(evaluation_experiments_table.c.id).where(
                evaluation_experiments_table.c.id == "experiment-preserved"
            )
        ).scalar_one_or_none()
    return (project_id, knowledge_count, experiment_id) == (
        PROJECT_ID,
        PROJECT_ID,
        "experiment-preserved",
    )
