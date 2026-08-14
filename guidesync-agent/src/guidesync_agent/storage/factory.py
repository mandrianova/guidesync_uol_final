from __future__ import annotations

from sqlalchemy import Engine

from .config import database_url
from .database import (
    DatabaseEvaluationStore,
    DatabaseKnowledgeStore,
    DatabaseLLMTranscriptStore,
    DatabaseModelSettingsStore,
    DatabaseModelUsageStore,
    DatabaseProjectProfileStore,
    DatabaseProjectStore,
    DatabaseProjectWorkflowStore,
    DatabaseRunStore,
)
from .database_engine import create_database_engine


def database_engine() -> Engine:
    return create_database_engine(database_url())


def create_evaluation_store() -> DatabaseEvaluationStore:
    return DatabaseEvaluationStore(database_engine())


def create_run_store() -> DatabaseRunStore:
    return DatabaseRunStore(database_engine())


def create_project_store() -> DatabaseProjectStore:
    return DatabaseProjectStore(database_engine())


def create_project_profile_store() -> DatabaseProjectProfileStore:
    return DatabaseProjectProfileStore(database_engine())


def create_project_workflow_store() -> DatabaseProjectWorkflowStore:
    return DatabaseProjectWorkflowStore(database_engine())


def create_model_settings_store() -> DatabaseModelSettingsStore:
    return DatabaseModelSettingsStore(database_engine())


def create_model_usage_store() -> DatabaseModelUsageStore:
    return DatabaseModelUsageStore(database_engine())


def create_llm_transcript_store() -> DatabaseLLMTranscriptStore:
    return DatabaseLLMTranscriptStore(database_engine())


def create_knowledge_store() -> DatabaseKnowledgeStore:
    return DatabaseKnowledgeStore(database_engine())


def initialize_storage() -> None:
    create_evaluation_store().initialize()
    create_run_store().initialize()
    create_project_store().initialize()
    create_project_profile_store().initialize()
    create_project_workflow_store().initialize()
    create_model_settings_store().initialize()
    create_model_usage_store().initialize()
    create_llm_transcript_store().initialize()
    create_knowledge_store().initialize()
