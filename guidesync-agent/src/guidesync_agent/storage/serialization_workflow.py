from __future__ import annotations

from sqlalchemy.engine import Row

from guidesync_agent.schemas import (
    ChangeAnalysisWorkflowInput,
    ChangeAnalysisWorkflowResult,
    KnowledgeIndexWorkflowInput,
    KnowledgeIndexWorkflowResult,
    PostAnalysisKnowledgeRefreshInput,
    PostAnalysisKnowledgeRefreshResult,
    ProjectProfileWorkflowInput,
    ProjectProfileWorkflowResult,
    ProjectWorkflowRequestedBy,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProjectWorkflowTaskStatus,
    RepositorySyncWorkflowInput,
    RepositorySyncWorkflowResult,
)


def workflow_values(task: ProjectWorkflowTask) -> dict[str, object]:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "kind": task.kind.value,
        "status": task.status.value,
        "sequence": task.sequence,
        "depends_on_task_ids": task.depends_on_task_ids,
        "dedupe_key": task.dedupe_key,
        "requested_by": task.requested_by.value,
        "reason": task.reason,
        "input": task.input.model_dump(mode="json"),
        "result": task.result.model_dump(mode="json") if task.result is not None else None,
        "error_message": task.error_message,
        "warnings": task.warnings,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
    }

def workflow_task_from_row(row: Row) -> ProjectWorkflowTask:
    mapping = row._mapping
    kind = ProjectWorkflowTaskKind(mapping["kind"])
    return ProjectWorkflowTask(
        id=mapping["id"],
        project_id=mapping["project_id"],
        kind=kind,
        status=ProjectWorkflowTaskStatus(mapping["status"]),
        sequence=mapping["sequence"],
        depends_on_task_ids=list(mapping["depends_on_task_ids"]),
        dedupe_key=mapping["dedupe_key"],
        requested_by=ProjectWorkflowRequestedBy(mapping["requested_by"]),
        reason=mapping["reason"],
        input=workflow_input_from_payload(kind, mapping["input"]),
        result=workflow_result_from_payload(kind, mapping["result"]),
        error_message=mapping["error_message"],
        warnings=list(mapping["warnings"]),
        created_at=mapping["created_at"],
        started_at=mapping["started_at"],
        completed_at=mapping["completed_at"],
    )

def workflow_input_from_payload(
    kind: ProjectWorkflowTaskKind,
    payload: object,
) -> (
    RepositorySyncWorkflowInput
    | ProjectProfileWorkflowInput
    | KnowledgeIndexWorkflowInput
    | ChangeAnalysisWorkflowInput
    | PostAnalysisKnowledgeRefreshInput
):
    model_by_kind = {
        ProjectWorkflowTaskKind.REPOSITORY_SYNC: RepositorySyncWorkflowInput,
        ProjectWorkflowTaskKind.PROJECT_PROFILE: ProjectProfileWorkflowInput,
        ProjectWorkflowTaskKind.KNOWLEDGE_INDEX: KnowledgeIndexWorkflowInput,
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS: ChangeAnalysisWorkflowInput,
        ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH: PostAnalysisKnowledgeRefreshInput,
    }
    return model_by_kind[kind].model_validate(payload)

def workflow_result_from_payload(
    kind: ProjectWorkflowTaskKind,
    payload: object,
) -> (
    RepositorySyncWorkflowResult
    | ProjectProfileWorkflowResult
    | KnowledgeIndexWorkflowResult
    | ChangeAnalysisWorkflowResult
    | PostAnalysisKnowledgeRefreshResult
    | None
):
    if payload is None:
        return None
    model_by_kind = {
        ProjectWorkflowTaskKind.REPOSITORY_SYNC: RepositorySyncWorkflowResult,
        ProjectWorkflowTaskKind.PROJECT_PROFILE: ProjectProfileWorkflowResult,
        ProjectWorkflowTaskKind.KNOWLEDGE_INDEX: KnowledgeIndexWorkflowResult,
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS: ChangeAnalysisWorkflowResult,
        ProjectWorkflowTaskKind.POST_ANALYSIS_KNOWLEDGE_REFRESH: (
            PostAnalysisKnowledgeRefreshResult
        ),
    }
    return model_by_kind[kind].model_validate(payload)

def next_workflow_sequence(tasks: list[ProjectWorkflowTask], project_id: str) -> int:
    sequences = [task.sequence for task in tasks if task.project_id == project_id]
    return (max(sequences) + 1) if sequences else 1

def find_active_dedupe_task(
    tasks: list[ProjectWorkflowTask],
    project_id: str,
    dedupe_key: str,
) -> ProjectWorkflowTask | None:
    active_statuses = {
        ProjectWorkflowTaskStatus.QUEUED,
        ProjectWorkflowTaskStatus.RUNNING,
        ProjectWorkflowTaskStatus.BLOCKED,
    }
    return next(
        (
            task
            for task in tasks
            if task.project_id == project_id
            and task.dedupe_key == dedupe_key
            and task.status in active_statuses
        ),
        None,
    )

def project_has_running_workflow(tasks: list[ProjectWorkflowTask], project_id: str) -> bool:
    return any(
        task.project_id == project_id and task.status == ProjectWorkflowTaskStatus.RUNNING
        for task in tasks
    )

def workflow_dependencies_completed(
    task: ProjectWorkflowTask,
    task_by_id: dict[str, ProjectWorkflowTask],
) -> bool:
    return all(
        task_by_id.get(task_id) is not None
        and task_by_id[task_id].status == ProjectWorkflowTaskStatus.COMPLETED
        for task_id in task.depends_on_task_ids
    )
