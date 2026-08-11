from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Table, create_engine, delete, func, or_, select
from sqlalchemy.engine import Connection

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
    ProjectCleanupArtifact,
    ProjectCleanupProject,
    ProjectCleanupRepositoryCache,
    ProjectCleanupResource,
    ProjectCleanupResourceCount,
    ProjectCleanupState,
)

TERMINAL_RUN_STATUSES = {"cancelled", "completed", "failed"}
TERMINAL_WORKFLOW_STATUSES = {"cancelled", "completed", "failed"}


class ProjectCleanupActiveWorkError(RuntimeError):
    pass


class DatabaseProjectCleanupStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def preview_project(self, project_id: str) -> ProjectCleanupProject:
        with self.engine.begin() as connection:
            project = connection.execute(
                select(projects_table.c.name).where(projects_table.c.id == project_id)
            ).one_or_none()
            if project is None:
                return ProjectCleanupProject(
                    project_id=project_id,
                    state=ProjectCleanupState.ALREADY_ABSENT,
                )
            identifiers = project_identifiers(connection, [project_id])
            return ProjectCleanupProject(
                project_id=project_id,
                name=project.name,
                state=ProjectCleanupState.PRESENT,
                run_ids=identifiers.run_ids,
                experiment_ids=identifiers.experiment_ids,
                artifacts=project_artifacts(connection, identifiers.run_ids),
                repository_caches=repository_caches(connection, project_id),
                active_run_ids=active_run_ids(connection, project_id),
                active_workflow_task_ids=active_workflow_task_ids(connection, project_id),
                resource_counts=resource_counts(connection, project_id, identifiers),
            )

    def delete_projects(self, project_ids: Sequence[str]) -> list[ProjectCleanupResourceCount]:
        targets = sorted(set(project_ids))
        with self.engine.begin() as connection:
            connection.execute(
                select(projects_table.c.id)
                .where(projects_table.c.id.in_(targets))
                .with_for_update()
            ).all()
            active_runs = active_ids_for_projects(
                connection,
                report_runs_table,
                targets,
                TERMINAL_RUN_STATUSES,
            )
            active_tasks = active_ids_for_projects(
                connection,
                project_workflow_tasks_table,
                targets,
                TERMINAL_WORKFLOW_STATUSES,
            )
            if active_runs or active_tasks:
                raise ProjectCleanupActiveWorkError(active_work_message(active_runs, active_tasks))
            identifiers = project_identifiers(connection, targets)
            return delete_project_graph(connection, targets, identifiers)

    def cache_path_users(self, path: str, excluded_project_ids: Sequence[str]) -> list[str]:
        query = select(project_repositories_table.c.project_id).where(
            project_repositories_table.c.local_path == path
        )
        if excluded_project_ids:
            query = query.where(
                project_repositories_table.c.project_id.not_in(excluded_project_ids)
            )
        with self.engine.begin() as connection:
            return sorted(set(connection.execute(query).scalars().all()))


@dataclass(frozen=True)
class ProjectIdentifiers:
    run_ids: list[str]
    experiment_ids: list[str]
    node_ids: list[str]
    annotation_run_ids: list[str]
    conversation_ids: list[str]


def project_identifiers(
    connection: Connection,
    project_ids: Sequence[str],
) -> ProjectIdentifiers:
    run_ids = selected_ids(connection, report_runs_table, project_ids)
    experiment_ids = selected_ids(connection, evaluation_experiments_table, project_ids)
    node_ids = selected_ids(connection, knowledge_nodes_table, project_ids)
    annotation_run_ids = selected_ids(connection, knowledge_annotation_runs_table, project_ids)
    conversation_ids = (
        connection.execute(
            select(llm_conversations_table.c.id).where(
                or_(
                    llm_conversations_table.c.project_id.in_(project_ids),
                    llm_conversations_table.c.run_id.in_(run_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    return ProjectIdentifiers(
        run_ids=sorted(run_ids),
        experiment_ids=sorted(experiment_ids),
        node_ids=sorted(node_ids),
        annotation_run_ids=sorted(annotation_run_ids),
        conversation_ids=sorted(conversation_ids),
    )


def selected_ids(
    connection: Connection,
    table: Table,
    project_ids: Sequence[str],
) -> list[str]:
    return list(
        connection.execute(select(table.c.id).where(table.c.project_id.in_(project_ids))).scalars()
    )


def project_artifacts(
    connection: Connection,
    run_ids: Sequence[str],
) -> list[ProjectCleanupArtifact]:
    if not run_ids:
        return []
    rows = connection.execute(
        select(run_artifacts_table)
        .where(run_artifacts_table.c.run_id.in_(run_ids))
        .order_by(run_artifacts_table.c.run_id, run_artifacts_table.c.id)
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


def repository_caches(
    connection: Connection,
    project_id: str,
) -> list[ProjectCleanupRepositoryCache]:
    rows = connection.execute(
        select(project_repositories_table.c.id, project_repositories_table.c.local_path)
        .where(
            project_repositories_table.c.project_id == project_id,
            project_repositories_table.c.local_path.is_not(None),
        )
        .order_by(project_repositories_table.c.id)
    ).all()
    entries: list[ProjectCleanupRepositoryCache] = []
    for row in rows:
        shared = (
            connection.execute(
                select(project_repositories_table.c.project_id).where(
                    project_repositories_table.c.local_path == row.local_path,
                    project_repositories_table.c.project_id != project_id,
                )
            )
            .scalars()
            .all()
        )
        entries.append(
            ProjectCleanupRepositoryCache(
                repository_id=row.id,
                path=row.local_path,
                shared_project_ids=sorted(set(shared)),
                deletable=not shared,
            )
        )
    return entries


def active_run_ids(connection: Connection, project_id: str) -> list[str]:
    return active_ids_for_projects(
        connection,
        report_runs_table,
        [project_id],
        TERMINAL_RUN_STATUSES,
    )


def active_workflow_task_ids(connection: Connection, project_id: str) -> list[str]:
    return active_ids_for_projects(
        connection,
        project_workflow_tasks_table,
        [project_id],
        TERMINAL_WORKFLOW_STATUSES,
    )


def active_ids_for_projects(
    connection: Connection,
    table: Table,
    project_ids: Sequence[str],
    terminal_statuses: set[str],
) -> list[str]:
    return sorted(
        connection.execute(
            select(table.c.id).where(
                table.c.project_id.in_(project_ids),
                table.c.status.not_in(terminal_statuses),
            )
        )
        .scalars()
        .all()
    )


def resource_counts(
    connection: Connection,
    project_id: str,
    identifiers: ProjectIdentifiers,
) -> list[ProjectCleanupResourceCount]:
    project_ids = [project_id]
    conditions = project_resource_conditions(project_ids, identifiers)
    return [
        ProjectCleanupResourceCount(
            resource=resource, count=row_count(connection, table, condition)
        )
        for resource, table, condition in conditions
    ]


def project_resource_conditions(
    project_ids: Sequence[str],
    ids: ProjectIdentifiers,
) -> list[tuple[ProjectCleanupResource, Table, ColumnElement[bool]]]:
    def direct(table: Table) -> ColumnElement[bool]:
        return table.c.project_id.in_(project_ids)

    def by_run(table: Table) -> ColumnElement[bool]:
        return table.c.run_id.in_(ids.run_ids)

    def by_experiment(table: Table) -> ColumnElement[bool]:
        return table.c.experiment_id.in_(ids.experiment_ids)

    return [
        (ProjectCleanupResource.PROJECTS, projects_table, projects_table.c.id.in_(project_ids)),
        (
            ProjectCleanupResource.REPOSITORIES,
            project_repositories_table,
            direct(project_repositories_table),
        ),
        (
            ProjectCleanupResource.DOCUMENTATION,
            project_documentation_table,
            direct(project_documentation_table),
        ),
        (
            ProjectCleanupResource.PROJECT_PROFILES,
            project_profiles_table,
            direct(project_profiles_table),
        ),
        (ProjectCleanupResource.MODEL_PROFILES, model_profiles_table, direct(model_profiles_table)),
        (
            ProjectCleanupResource.WORKFLOW_TASKS,
            project_workflow_tasks_table,
            direct(project_workflow_tasks_table),
        ),
        (ProjectCleanupResource.REPORT_RUNS, report_runs_table, direct(report_runs_table)),
        (ProjectCleanupResource.RUN_EVENTS, run_events_table, by_run(run_events_table)),
        (ProjectCleanupResource.RUN_ARTIFACTS, run_artifacts_table, by_run(run_artifacts_table)),
        (ProjectCleanupResource.EVIDENCE_ITEMS, evidence_items_table, by_run(evidence_items_table)),
        (
            ProjectCleanupResource.CHANGE_CLASSIFICATIONS,
            change_classifications_table,
            by_run(change_classifications_table),
        ),
        (ProjectCleanupResource.SCREENSHOTS, screenshots_table, by_run(screenshots_table)),
        (
            ProjectCleanupResource.EVALUATION_EXPERIMENTS,
            evaluation_experiments_table,
            direct(evaluation_experiments_table),
        ),
        (
            ProjectCleanupResource.EVALUATION_RUNS,
            evaluation_runs_table,
            by_experiment(evaluation_runs_table),
        ),
        (
            ProjectCleanupResource.EVALUATION_COMPARISONS,
            evaluation_comparisons_table,
            by_experiment(evaluation_comparisons_table),
        ),
        (
            ProjectCleanupResource.KNOWLEDGE_INDEX_RUNS,
            knowledge_index_runs_table,
            direct(knowledge_index_runs_table),
        ),
        (
            ProjectCleanupResource.KNOWLEDGE_NODES,
            knowledge_nodes_table,
            direct(knowledge_nodes_table),
        ),
        (
            ProjectCleanupResource.KNOWLEDGE_EDGES,
            knowledge_edges_table,
            or_(
                direct(knowledge_edges_table),
                knowledge_edges_table.c.source_node_id.in_(ids.node_ids),
                knowledge_edges_table.c.target_node_id.in_(ids.node_ids),
            ),
        ),
        (
            ProjectCleanupResource.KNOWLEDGE_CHUNKS,
            knowledge_chunks_table,
            or_(
                direct(knowledge_chunks_table),
                knowledge_chunks_table.c.node_id.in_(ids.node_ids),
            ),
        ),
        (
            ProjectCleanupResource.KNOWLEDGE_ANNOTATION_RUNS,
            knowledge_annotation_runs_table,
            direct(knowledge_annotation_runs_table),
        ),
        (
            ProjectCleanupResource.KNOWLEDGE_ANNOTATIONS,
            knowledge_annotations_table,
            or_(
                direct(knowledge_annotations_table),
                knowledge_annotations_table.c.run_id.in_(ids.annotation_run_ids),
            ),
        ),
        (
            ProjectCleanupResource.KNOWLEDGE_CONCEPTS,
            knowledge_concepts_table,
            direct(knowledge_concepts_table),
        ),
        (
            ProjectCleanupResource.KNOWLEDGE_ANNOTATION_EDGES,
            knowledge_annotation_edges_table,
            or_(
                direct(knowledge_annotation_edges_table),
                knowledge_annotation_edges_table.c.annotation_run_id.in_(ids.annotation_run_ids),
            ),
        ),
        (
            ProjectCleanupResource.LLM_CONVERSATIONS,
            llm_conversations_table,
            llm_conversations_table.c.id.in_(ids.conversation_ids),
        ),
        (
            ProjectCleanupResource.LLM_CONVERSATION_EVENTS,
            llm_conversation_events_table,
            llm_conversation_events_table.c.conversation_id.in_(ids.conversation_ids),
        ),
        (
            ProjectCleanupResource.MODEL_CALL_LEDGER,
            model_call_ledger_table,
            or_(direct(model_call_ledger_table), by_run(model_call_ledger_table)),
        ),
    ]


def row_count(connection: Connection, table: Table, condition: ColumnElement[bool]) -> int:
    return connection.execute(select(func.count()).select_from(table).where(condition)).scalar_one()


def delete_project_graph(
    connection: Connection,
    project_ids: Sequence[str],
    ids: ProjectIdentifiers,
) -> list[ProjectCleanupResourceCount]:
    conditions = project_resource_conditions(project_ids, ids)
    by_resource = {resource: (table, condition) for resource, table, condition in conditions}
    order = [
        ProjectCleanupResource.LLM_CONVERSATION_EVENTS,
        ProjectCleanupResource.LLM_CONVERSATIONS,
        ProjectCleanupResource.MODEL_CALL_LEDGER,
        ProjectCleanupResource.WORKFLOW_TASKS,
        ProjectCleanupResource.RUN_EVENTS,
        ProjectCleanupResource.RUN_ARTIFACTS,
        ProjectCleanupResource.EVIDENCE_ITEMS,
        ProjectCleanupResource.CHANGE_CLASSIFICATIONS,
        ProjectCleanupResource.SCREENSHOTS,
        ProjectCleanupResource.REPORT_RUNS,
        ProjectCleanupResource.EVALUATION_COMPARISONS,
        ProjectCleanupResource.EVALUATION_RUNS,
        ProjectCleanupResource.EVALUATION_EXPERIMENTS,
        ProjectCleanupResource.KNOWLEDGE_ANNOTATION_EDGES,
        ProjectCleanupResource.KNOWLEDGE_ANNOTATIONS,
        ProjectCleanupResource.KNOWLEDGE_ANNOTATION_RUNS,
        ProjectCleanupResource.KNOWLEDGE_CHUNKS,
        ProjectCleanupResource.KNOWLEDGE_EDGES,
        ProjectCleanupResource.KNOWLEDGE_CONCEPTS,
        ProjectCleanupResource.KNOWLEDGE_NODES,
        ProjectCleanupResource.KNOWLEDGE_INDEX_RUNS,
        ProjectCleanupResource.PROJECT_PROFILES,
        ProjectCleanupResource.MODEL_PROFILES,
        ProjectCleanupResource.DOCUMENTATION,
        ProjectCleanupResource.REPOSITORIES,
        ProjectCleanupResource.PROJECTS,
    ]
    return [delete_resource(connection, resource, *by_resource[resource]) for resource in order]


def delete_resource(
    connection: Connection,
    resource: ProjectCleanupResource,
    table: Table,
    condition: ColumnElement[bool],
) -> ProjectCleanupResourceCount:
    result = connection.execute(delete(table).where(condition))
    return ProjectCleanupResourceCount(resource=resource, count=max(result.rowcount or 0, 0))


def active_work_message(active_runs: list[str], active_tasks: list[str]) -> str:
    parts = []
    if active_runs:
        parts.append("non-terminal report runs: " + ", ".join(active_runs))
    if active_tasks:
        parts.append("non-terminal workflow tasks: " + ", ".join(active_tasks))
    return "Project cleanup refused because active work exists (" + "; ".join(parts) + ")."
