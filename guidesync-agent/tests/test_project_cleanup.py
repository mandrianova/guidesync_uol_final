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
    change_classifications_table,
    evaluation_comparisons_table,
    evaluation_experiments_table,
    evaluation_runs_table,
    evidence_items_table,
    knowledge_annotation_edges_table,
    knowledge_annotation_runs_table,
    knowledge_annotations_table,
    knowledge_chunks_table,
    knowledge_concepts_table,
    knowledge_edges_table,
    knowledge_index_runs_table,
    knowledge_nodes_table,
    llm_conversation_events_table,
    llm_conversations_table,
    model_call_ledger_table,
    model_profiles_table,
    project_documentation_table,
    project_profiles_table,
    project_repositories_table,
    project_workflow_tasks_table,
    projects_table,
    report_runs_table,
    run_artifacts_table,
    run_events_table,
    screenshots_table,
)
from guidesync_agent.schemas.project_cleanup import (
    ProjectCleanupRequest,
    ProjectCleanupResource,
    ProjectCleanupState,
)
from guidesync_agent.services.project_cleanup import (
    ProjectCleanupPlanError,
    ProjectCleanupService,
)
from guidesync_agent.storage.database_project_cleanup import DatabaseProjectCleanupStore

TARGET_ID = "project-cleanup-target"
PROTECTED_ID = "project-cleanup-protected"
RUN_ID = "run-cleanup-target"
EXPERIMENT_ID = "experiment-cleanup-target"


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


def test_cleanup_preview_and_apply_full_project_graph(tmp_path: Path) -> None:
    cache_root = tmp_path / "repositories"
    cache_path = cache_root / "target" / "repo"
    cache_path.mkdir(parents=True)
    (cache_path / "README.md").write_text("cached", encoding="utf-8")
    store = cleanup_store(tmp_path)
    seed_project_graph(store, cache_path)
    s3 = FakeS3Client(
        {
            f"reports/{RUN_ID}/run.json",
            f"reports/{RUN_ID}/unregistered-debug.json",
            "reports/protected-run/run.json",
        }
    )
    service = cleanup_service(store, cache_root, s3)
    request = ProjectCleanupRequest(
        target_project_ids=[TARGET_ID],
        protected_project_ids=[PROTECTED_ID],
    )

    plan = service.preview(request)

    counts = {item.resource: item.count for item in plan.projects[0].resource_counts}
    assert plan.safe_to_apply is True
    assert plan.projects[0].s3_keys == [
        f"reports/{RUN_ID}/run.json",
        f"reports/{RUN_ID}/unregistered-debug.json",
    ]
    assert all(counts[resource] == 1 for resource in ProjectCleanupResource)
    assert plan.projects[0].repository_caches[0].deletable is True

    result = service.apply(plan, plan.checksum)

    assert result.complete is True
    assert result.deleted_project_ids == [TARGET_ID]
    assert result.already_absent_project_ids == []
    assert cache_path.exists() is False
    assert s3.keys == {"reports/protected-run/run.json"}
    assert store.preview_project(TARGET_ID).state is ProjectCleanupState.ALREADY_ABSENT
    assert store.preview_project(PROTECTED_ID).state is ProjectCleanupState.PRESENT
    assert global_model_profile_exists(store)

    repeated_plan = service.preview(request)
    repeated = service.apply(repeated_plan, repeated_plan.checksum)
    assert repeated.deleted_project_ids == []
    assert repeated.already_absent_project_ids == [TARGET_ID]
    assert repeated.complete is True


def test_cleanup_refuses_non_terminal_run(tmp_path: Path) -> None:
    store = cleanup_store(tmp_path)
    seed_project_graph(store, tmp_path / "repositories" / "target", run_status="blocked")
    service = cleanup_service(store, tmp_path / "repositories", FakeS3Client(set()))
    request = ProjectCleanupRequest(
        target_project_ids=[TARGET_ID],
        protected_project_ids=[PROTECTED_ID],
    )

    plan = service.preview(request)

    assert plan.safe_to_apply is False
    assert plan.projects[0].active_run_ids == [RUN_ID]
    with pytest.raises(ProjectCleanupPlanError, match="non-terminal work"):
        service.apply(plan, plan.checksum)
    assert store.preview_project(TARGET_ID).state is ProjectCleanupState.PRESENT


def test_cleanup_refuses_non_terminal_workflow_task(tmp_path: Path) -> None:
    store = cleanup_store(tmp_path)
    seed_project_graph(
        store,
        tmp_path / "repositories" / "target",
        workflow_status="retrying",
    )
    service = cleanup_service(store, tmp_path / "repositories", FakeS3Client(set()))

    plan = service.preview(
        ProjectCleanupRequest(
            target_project_ids=[TARGET_ID],
            protected_project_ids=[PROTECTED_ID],
        )
    )

    assert plan.safe_to_apply is False
    assert plan.projects[0].active_workflow_task_ids
    with pytest.raises(ProjectCleanupPlanError, match="non-terminal work"):
        service.apply(plan, plan.checksum)


def test_cleanup_rejects_allowlisted_target() -> None:
    with pytest.raises(ValidationError, match="Protected projects"):
        ProjectCleanupRequest(
            target_project_ids=[TARGET_ID],
            protected_project_ids=[TARGET_ID],
        )


def test_cleanup_requires_exact_plan_checksum(tmp_path: Path) -> None:
    store = cleanup_store(tmp_path)
    seed_project_graph(store, tmp_path / "repositories" / "target")
    service = cleanup_service(store, tmp_path / "repositories", FakeS3Client(set()))
    plan = service.preview(
        ProjectCleanupRequest(
            target_project_ids=[TARGET_ID],
            protected_project_ids=[PROTECTED_ID],
        )
    )

    with pytest.raises(ProjectCleanupPlanError, match="exactly match"):
        service.apply(plan, "wrong-checksum")


def cleanup_store(tmp_path: Path) -> DatabaseProjectCleanupStore:
    store = DatabaseProjectCleanupStore(sqlite_database_url(tmp_path / "cleanup.db"))

    @event.listens_for(store.engine, "connect")
    def enable_foreign_keys(dbapi_connection: SQLiteConnection, _: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return store


def cleanup_service(
    store: DatabaseProjectCleanupStore,
    cache_root: Path,
    s3: FakeS3Client,
) -> ProjectCleanupService:
    return ProjectCleanupService(
        store,
        ArtifactStorageConfig(
            bucket="guidesync-test-artifacts",
            endpoint_url="http://minio.invalid",
            prefix="reports",
        ),
        cache_root,
        s3,
    )


def seed_project_graph(
    store: DatabaseProjectCleanupStore,
    cache_path: Path,
    *,
    run_status: str = "completed",
    workflow_status: str = "completed",
) -> None:
    now = datetime.now(UTC)
    with store.engine.begin() as connection:
        add_row(connection, projects_table, {"id": PROTECTED_ID, "name": "Protected"})
        add_row(connection, projects_table, {"id": TARGET_ID, "name": "Target"})
        add_row(
            connection,
            model_profiles_table,
            {"id": "global-model", "project_id": None, "name": "Global model"},
        )
        add_row(
            connection,
            project_repositories_table,
            {
                "id": "repo-target",
                "project_id": TARGET_ID,
                "local_path": str(cache_path),
            },
        )
        add_row(connection, project_documentation_table, {"project_id": TARGET_ID})
        add_row(connection, project_profiles_table, {"project_id": TARGET_ID})
        add_row(connection, model_profiles_table, {"project_id": TARGET_ID})
        add_row(
            connection,
            project_workflow_tasks_table,
            {"project_id": TARGET_ID, "status": workflow_status},
        )
        add_row(
            connection,
            report_runs_table,
            {"id": RUN_ID, "project_id": TARGET_ID, "status": run_status},
        )
        add_run_rows(connection)
        add_evaluation_rows(connection)
        add_knowledge_rows(connection)
        add_llm_rows(connection, now)


def add_run_rows(connection: Connection) -> None:
    overrides = {"run_id": RUN_ID}
    add_row(connection, run_events_table, overrides)
    add_row(
        connection,
        run_artifacts_table,
        {
            **overrides,
            "artifact_type": "run.json",
            "uri": f"s3://guidesync-test-artifacts/reports/{RUN_ID}/run.json",
        },
    )
    add_row(connection, evidence_items_table, overrides)
    add_row(connection, change_classifications_table, overrides)
    add_row(connection, screenshots_table, overrides)


def add_evaluation_rows(connection: Connection) -> None:
    add_row(
        connection,
        evaluation_experiments_table,
        {"id": EXPERIMENT_ID, "project_id": TARGET_ID},
    )
    add_row(connection, evaluation_runs_table, {"experiment_id": EXPERIMENT_ID})
    add_row(connection, evaluation_comparisons_table, {"experiment_id": EXPERIMENT_ID})


def add_knowledge_rows(connection: Connection) -> None:
    add_row(connection, knowledge_index_runs_table, {"project_id": TARGET_ID})
    add_row(connection, knowledge_nodes_table, {"id": "node-target", "project_id": TARGET_ID})
    add_row(
        connection,
        knowledge_edges_table,
        {
            "project_id": None,
            "source_node_id": "node-target",
            "target_node_id": "node-target",
        },
    )
    add_row(
        connection,
        knowledge_chunks_table,
        {"project_id": None, "node_id": "node-target"},
    )
    add_row(
        connection,
        knowledge_annotation_runs_table,
        {"id": "annotation-run-target", "project_id": TARGET_ID},
    )
    add_row(
        connection,
        knowledge_annotations_table,
        {"project_id": None, "run_id": "annotation-run-target"},
    )
    add_row(connection, knowledge_concepts_table, {"project_id": TARGET_ID})
    add_row(
        connection,
        knowledge_annotation_edges_table,
        {"project_id": None, "annotation_run_id": "annotation-run-target"},
    )


def add_llm_rows(connection: Connection, now: datetime) -> None:
    add_row(
        connection,
        llm_conversations_table,
        {
            "id": "conversation-target",
            "project_id": TARGET_ID,
            "run_id": RUN_ID,
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
        {"project_id": TARGET_ID, "run_id": RUN_ID, "started_at": now},
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


def global_model_profile_exists(store: DatabaseProjectCleanupStore) -> bool:
    with store.engine.begin() as connection:
        return (
            connection.execute(
                select(model_profiles_table.c.id).where(model_profiles_table.c.id == "global-model")
            ).scalar_one_or_none()
            == "global-model"
        )
