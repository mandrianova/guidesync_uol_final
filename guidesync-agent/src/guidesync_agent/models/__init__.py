from __future__ import annotations

from .base import metadata
from .knowledge import (
    knowledge_annotation_edges_table,
    knowledge_annotation_runs_table,
    knowledge_annotations_table,
    knowledge_chunks_table,
    knowledge_concepts_table,
    knowledge_edges_table,
    knowledge_index_runs_table,
    knowledge_nodes_table,
)
from .projects import (
    model_profiles_table,
    project_documentation_table,
    project_profiles_table,
    project_repositories_table,
    projects_table,
)
from .runs import (
    change_classifications_table,
    evidence_items_table,
    report_runs_table,
    run_artifacts_table,
    run_events_table,
    screenshots_table,
)
from .workflow import project_workflow_tasks_table

__all__ = [
    "metadata",
    "model_profiles_table",
    "projects_table",
    "project_repositories_table",
    "project_documentation_table",
    "project_profiles_table",
    "report_runs_table",
    "run_events_table",
    "run_artifacts_table",
    "evidence_items_table",
    "change_classifications_table",
    "screenshots_table",
    "knowledge_index_runs_table",
    "knowledge_nodes_table",
    "knowledge_edges_table",
    "knowledge_chunks_table",
    "knowledge_annotation_runs_table",
    "knowledge_annotations_table",
    "knowledge_concepts_table",
    "knowledge_annotation_edges_table",
    "project_workflow_tasks_table",
]
