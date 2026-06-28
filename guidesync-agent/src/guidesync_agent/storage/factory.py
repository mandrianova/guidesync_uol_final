from __future__ import annotations

from .config import database_url
from .database import (
    DatabaseKnowledgeStore,
    DatabaseLLMTranscriptStore,
    DatabaseModelSettingsStore,
    DatabaseModelUsageStore,
    DatabaseProjectProfileStore,
    DatabaseProjectStore,
    DatabaseProjectWorkflowStore,
    DatabaseRunStore,
)
from .protocols import (
    KnowledgeStore,
    LLMTranscriptStore,
    ModelSettingsStore,
    ModelUsageStore,
    ProjectProfileStore,
    ProjectStore,
    ProjectWorkflowStore,
    RunStore,
)


def create_run_store() -> RunStore:
    return DatabaseRunStore(database_url())


def create_project_store() -> ProjectStore:
    return DatabaseProjectStore(database_url())


def create_project_profile_store() -> ProjectProfileStore:
    return DatabaseProjectProfileStore(database_url())


def create_project_workflow_store() -> ProjectWorkflowStore:
    return DatabaseProjectWorkflowStore(database_url())


def create_model_settings_store() -> ModelSettingsStore:
    return DatabaseModelSettingsStore(database_url())


def create_model_usage_store() -> ModelUsageStore:
    return DatabaseModelUsageStore(database_url())


def create_llm_transcript_store() -> LLMTranscriptStore:
    return DatabaseLLMTranscriptStore(database_url())


def create_knowledge_store() -> KnowledgeStore:
    return DatabaseKnowledgeStore(database_url())


def initialize_storage() -> None:
    create_run_store().initialize()
    create_project_store().initialize()
    create_project_profile_store().initialize()
    create_project_workflow_store().initialize()
    create_model_settings_store().initialize()
    create_model_usage_store().initialize()
    create_llm_transcript_store().initialize()
    create_knowledge_store().initialize()
