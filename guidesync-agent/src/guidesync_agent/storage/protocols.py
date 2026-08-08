from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from guidesync_agent.schemas import (
    AblationComparisonReport,
    EvaluationComparisonPage,
    EvaluationComparisonRecord,
    EvaluationExperimentManifest,
    EvaluationExperimentPage,
    EvaluationExperimentRecord,
    EvaluationExperimentRun,
    EvaluationRunPage,
    EvaluationRunRecord,
    EvaluationRunStatus,
    GuideSyncRunResult,
    KnowledgeDocumentRefs,
    KnowledgeEdge,
    KnowledgeGraphSnapshot,
    KnowledgeIndexRun,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    KnowledgeTag,
    LLMConversationTranscript,
    LLMTranscriptEvent,
    LLMTranscriptSummary,
    ModelCallLedgerEntry,
    ModelSettings,
    ModelSettingsUpdate,
    ProjectConfig,
    ProjectCreate,
    ProjectProfileSnapshot,
    ProjectWorkflowProgress,
    ProjectWorkflowTask,
    ProviderConfig,
    RetrievalEvaluationSnapshot,
    RunCancellationResult,
    RunSummary,
    RunTokenUsageSummary,
    WorkflowTaskTokenUsageSummary,
)


class EvaluationStore(Protocol):
    def initialize(self) -> None: ...

    def save_experiment(
        self,
        project_id: str,
        manifest: EvaluationExperimentManifest,
        manifest_checksum: str,
    ) -> EvaluationExperimentRecord: ...

    def get_experiment(self, experiment_id: str) -> EvaluationExperimentRecord | None: ...

    def list_experiments(
        self,
        project_id: str,
        *,
        limit: int,
        offset: int,
    ) -> EvaluationExperimentPage: ...

    def save_run(self, run: EvaluationExperimentRun) -> EvaluationRunRecord: ...

    def list_runs(  # noqa: PLR0913 - explicit storage query contract
        self,
        experiment_id: str,
        *,
        case_id: str | None,
        condition_id: str | None,
        status: EvaluationRunStatus | None,
        limit: int,
        offset: int,
    ) -> EvaluationRunPage: ...

    def save_comparison(
        self,
        comparison_id: str,
        report: AblationComparisonReport,
    ) -> EvaluationComparisonRecord: ...

    def list_comparisons(
        self,
        experiment_id: str,
        *,
        limit: int,
        offset: int,
    ) -> EvaluationComparisonPage: ...


class RunStore(Protocol):
    def initialize(self) -> None: ...

    def save(self, result: GuideSyncRunResult) -> None: ...

    def get(self, run_id: str) -> GuideSyncRunResult | None: ...

    def list_runs(self, project_id: str | None = None) -> list[RunSummary]: ...

    def claim_next_queued_run(self) -> GuideSyncRunResult | None: ...

    def record_run_event(
        self,
        run_id: str,
        status: str,
        message: str,
        stage: str | None = None,
    ) -> None: ...


class ProjectStore(Protocol):
    def initialize(self) -> None: ...

    def list_projects(self) -> list[ProjectConfig]: ...

    def save(self, project: ProjectCreate, project_id: str | None = None) -> ProjectConfig: ...

    def get(self, project_id: str) -> ProjectConfig | None: ...


class ProjectProfileStore(Protocol):
    def initialize(self) -> None: ...

    def save(self, profile: ProjectProfileSnapshot) -> ProjectProfileSnapshot: ...

    def get(self, profile_id: str) -> ProjectProfileSnapshot | None: ...

    def latest(self, project_id: str) -> ProjectProfileSnapshot | None: ...

    def list_profiles(self, project_id: str) -> list[ProjectProfileSnapshot]: ...


class ProjectWorkflowStore(Protocol):
    def initialize(self) -> None: ...

    def enqueue(self, task: ProjectWorkflowTask) -> ProjectWorkflowTask: ...

    def save(self, task: ProjectWorkflowTask) -> ProjectWorkflowTask: ...

    def get(self, task_id: str) -> ProjectWorkflowTask | None: ...

    def list_tasks(self, project_id: str | None = None) -> list[ProjectWorkflowTask]: ...

    def claim_next(self) -> ProjectWorkflowTask | None: ...

    def heartbeat(
        self,
        task_id: str,
        lease_token: str,
        progress: ProjectWorkflowProgress | None = None,
    ) -> bool: ...

    def cancel_run(
        self,
        run_id: str,
        *,
        reason: str,
    ) -> RunCancellationResult: ...


class ModelSettingsStore(Protocol):
    def initialize(self) -> None: ...

    def get(self) -> ModelSettings: ...

    def list_profiles(self) -> list[ModelSettings]: ...

    def save(self, settings: ModelSettingsUpdate) -> ModelSettings: ...

    def save_profile(
        self,
        settings: ModelSettingsUpdate,
        profile_id: str | None = None,
        make_default: bool = False,
    ) -> ModelSettings: ...

    def set_default(self, profile_id: str) -> ModelSettings | None: ...

    def delete_profile(self, profile_id: str) -> ModelSettings | None: ...

    def provider_config(self) -> ProviderConfig: ...


class LLMTranscriptStore(Protocol):
    def initialize(self) -> None: ...

    def save(self, transcript: LLMConversationTranscript) -> LLMConversationTranscript: ...

    def save_event(self, event: LLMTranscriptEvent) -> LLMTranscriptEvent: ...

    def save_events(self, events: Sequence[LLMTranscriptEvent]) -> list[LLMTranscriptEvent]: ...

    def get(self, transcript_id: str) -> LLMConversationTranscript | None: ...

    def list_events(self, transcript_id: str) -> list[LLMTranscriptEvent]: ...

    def list_for_run(self, run_id: str) -> list[LLMTranscriptSummary]: ...

    def list_for_workflow_task(self, workflow_task_id: str) -> list[LLMTranscriptSummary]: ...


class ModelUsageStore(Protocol):
    def initialize(self) -> None: ...

    def record(self, entry: ModelCallLedgerEntry) -> ModelCallLedgerEntry: ...

    def list_for_run(
        self,
        run_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ModelCallLedgerEntry]: ...

    def summarize_run(self, run_id: str) -> RunTokenUsageSummary: ...

    def summarize_workflow_task(
        self,
        workflow_task_id: str,
    ) -> WorkflowTaskTokenUsageSummary: ...


class KnowledgeStore(Protocol):
    def initialize(self) -> None: ...

    def save_snapshot(self, snapshot: KnowledgeGraphSnapshot) -> None: ...

    def save_changed_docs_snapshot(
        self,
        snapshot: KnowledgeGraphSnapshot,
        changed_paths: set[str],
    ) -> None: ...

    def get_index_run(self, run_id: str) -> KnowledgeIndexRun | None: ...

    def list_index_runs(self, project_id: str | None = None) -> list[KnowledgeIndexRun]: ...

    def search(self, request: KnowledgeSearchRequest) -> list[KnowledgeSearchResult]: ...

    def document_refs(self, project_id: str | None = None) -> KnowledgeDocumentRefs: ...

    def tag_cloud(self, project_id: str | None = None) -> list[KnowledgeTag]: ...

    def related_edges(
        self,
        node_ids: set[str],
        project_id: str | None = None,
    ) -> list[KnowledgeEdge]: ...

    def retrieval_evaluation_snapshot(
        self,
        project_id: str | None,
    ) -> RetrievalEvaluationSnapshot: ...
