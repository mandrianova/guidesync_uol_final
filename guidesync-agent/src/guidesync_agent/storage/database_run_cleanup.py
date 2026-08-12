from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import ColumnElement, Table, create_engine, delete, func, select
from sqlalchemy.engine import Connection

from guidesync_agent.models import (
    change_classifications_table,
    evaluation_comparisons_table,
    evaluation_experiments_table,
    evaluation_runs_table,
    evidence_items_table,
    llm_conversation_events_table,
    llm_conversations_table,
    model_call_ledger_table,
    project_workflow_tasks_table,
    report_runs_table,
    run_artifacts_table,
    run_events_table,
    screenshots_table,
)
from guidesync_agent.schemas.project_cleanup import (
    ProjectCleanupArtifact,
    ProjectCleanupResource,
    ProjectCleanupResourceCount,
    ProjectCleanupState,
)
from guidesync_agent.schemas.run_cleanup import RunCleanupRun

TERMINAL_RUN_STATUSES = {"cancelled", "completed", "failed", "partial_failure"}
TERMINAL_WORKFLOW_STATUSES = {"cancelled", "completed", "failed"}


class RunCleanupActiveWorkError(RuntimeError):
    pass


class DatabaseRunCleanupStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def preview_run(self, run_id: str) -> RunCleanupRun:
        with self.engine.begin() as connection:
            row = connection.execute(
                select(
                    report_runs_table.c.project_id,
                    report_runs_table.c.status,
                    report_runs_table.c.publication_snapshot,
                ).where(report_runs_table.c.id == run_id)
            ).one_or_none()
            if row is None:
                return RunCleanupRun(
                    run_id=run_id,
                    state=ProjectCleanupState.ALREADY_ABSENT,
                )
            return RunCleanupRun(
                run_id=run_id,
                project_id=row.project_id,
                status=row.status,
                state=ProjectCleanupState.PRESENT,
                publication_available=row.publication_snapshot is not None,
                artifacts=run_artifacts(connection, run_id),
                active_workflow_task_ids=active_workflow_task_ids(connection, run_id),
                evaluation_reference_ids=evaluation_reference_ids(connection, run_id),
                resource_counts=run_resource_counts(connection, run_id),
            )

    def delete_runs(self, run_ids: Sequence[str]) -> list[ProjectCleanupResourceCount]:
        targets = sorted(set(run_ids))
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(
                    report_runs_table.c.id,
                    report_runs_table.c.status,
                    report_runs_table.c.publication_snapshot,
                )
                .where(report_runs_table.c.id.in_(targets))
                .with_for_update()
            ).all()
            blocked = [
                row.id
                for row in rows
                if row.status not in TERMINAL_RUN_STATUSES or row.publication_snapshot is not None
            ]
            active_tasks = [
                task_id
                for run_id in targets
                for task_id in active_workflow_task_ids(connection, run_id)
            ]
            evaluation_refs = [
                reference
                for run_id in targets
                for reference in evaluation_reference_ids(connection, run_id)
            ]
            if blocked or active_tasks or evaluation_refs:
                details = blocked + active_tasks + evaluation_refs
                raise RunCleanupActiveWorkError(
                    "Run cleanup refused because protected or active data exists: "
                    + ", ".join(details)
                )
            return delete_run_graph(connection, [row.id for row in rows])


def workflow_run_condition(run_id: str) -> ColumnElement[bool]:
    return project_workflow_tasks_table.c.input["run_id"].as_string() == run_id


def active_workflow_task_ids(connection: Connection, run_id: str) -> list[str]:
    return sorted(
        connection.execute(
            select(project_workflow_tasks_table.c.id).where(
                workflow_run_condition(run_id),
                project_workflow_tasks_table.c.status.not_in(TERMINAL_WORKFLOW_STATUSES),
            )
        )
        .scalars()
        .all()
    )


def run_artifacts(connection: Connection, run_id: str) -> list[ProjectCleanupArtifact]:
    rows = connection.execute(
        select(run_artifacts_table)
        .where(run_artifacts_table.c.run_id == run_id)
        .order_by(run_artifacts_table.c.id)
    ).all()
    return [
        ProjectCleanupArtifact(
            id=row.id,
            run_id=row.run_id,
            artifact_type=row.artifact_type,
            uri=row.uri,
        )
        for row in rows
    ]


def evaluation_reference_ids(connection: Connection, run_id: str) -> list[str]:
    references: list[str] = []
    sources = [
        ("experiment", evaluation_experiments_table, evaluation_experiments_table.c.manifest),
        ("evaluation-run", evaluation_runs_table, evaluation_runs_table.c.payload),
        ("comparison", evaluation_comparisons_table, evaluation_comparisons_table.c.payload),
    ]
    for label, table, payload_column in sources:
        for row in connection.execute(select(table.c.id, payload_column)).all():
            if contains_value(row[1], run_id):
                references.append(f"{label}:{row.id}")
    return sorted(references)


def contains_value(value: object, target: str) -> bool:
    if isinstance(value, dict):
        return any(contains_value(item, target) for item in value.values())
    if isinstance(value, list):
        return any(contains_value(item, target) for item in value)
    return value == target


def run_resource_conditions(
    run_ids: Sequence[str],
) -> list[tuple[ProjectCleanupResource, Table, ColumnElement[bool]]]:
    by_run = report_runs_table.c.id.in_(run_ids)
    conversation_ids = select(llm_conversations_table.c.id).where(
        llm_conversations_table.c.run_id.in_(run_ids)
    )
    workflow_condition = project_workflow_tasks_table.c.input["run_id"].as_string().in_(run_ids)
    return [
        (
            ProjectCleanupResource.LLM_CONVERSATION_EVENTS,
            llm_conversation_events_table,
            llm_conversation_events_table.c.conversation_id.in_(conversation_ids),
        ),
        (
            ProjectCleanupResource.LLM_CONVERSATIONS,
            llm_conversations_table,
            llm_conversations_table.c.run_id.in_(run_ids),
        ),
        (
            ProjectCleanupResource.MODEL_CALL_LEDGER,
            model_call_ledger_table,
            model_call_ledger_table.c.run_id.in_(run_ids),
        ),
        (
            ProjectCleanupResource.WORKFLOW_TASKS,
            project_workflow_tasks_table,
            workflow_condition,
        ),
        (
            ProjectCleanupResource.RUN_EVENTS,
            run_events_table,
            run_events_table.c.run_id.in_(run_ids),
        ),
        (
            ProjectCleanupResource.RUN_ARTIFACTS,
            run_artifacts_table,
            run_artifacts_table.c.run_id.in_(run_ids),
        ),
        (
            ProjectCleanupResource.EVIDENCE_ITEMS,
            evidence_items_table,
            evidence_items_table.c.run_id.in_(run_ids),
        ),
        (
            ProjectCleanupResource.CHANGE_CLASSIFICATIONS,
            change_classifications_table,
            change_classifications_table.c.run_id.in_(run_ids),
        ),
        (
            ProjectCleanupResource.SCREENSHOTS,
            screenshots_table,
            screenshots_table.c.run_id.in_(run_ids),
        ),
        (ProjectCleanupResource.REPORT_RUNS, report_runs_table, by_run),
    ]


def run_resource_counts(connection: Connection, run_id: str) -> list[ProjectCleanupResourceCount]:
    return [
        ProjectCleanupResourceCount(
            resource=resource,
            count=connection.execute(
                select(func.count()).select_from(table).where(condition)
            ).scalar_one(),
        )
        for resource, table, condition in run_resource_conditions([run_id])
    ]


def delete_run_graph(
    connection: Connection,
    run_ids: Sequence[str],
) -> list[ProjectCleanupResourceCount]:
    deleted: list[ProjectCleanupResourceCount] = []
    for resource, table, condition in run_resource_conditions(run_ids):
        result = connection.execute(delete(table).where(condition))
        deleted.append(
            ProjectCleanupResourceCount(
                resource=resource,
                count=max(result.rowcount or 0, 0),
            )
        )
    return deleted
