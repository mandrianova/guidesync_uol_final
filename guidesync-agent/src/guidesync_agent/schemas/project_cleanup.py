from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class ProjectCleanupState(StrEnum):
    PRESENT = "present"
    ALREADY_ABSENT = "already_absent"


class ProjectCleanupResource(StrEnum):
    PROJECTS = "projects"
    REPOSITORIES = "repositories"
    DOCUMENTATION = "documentation"
    PROJECT_PROFILES = "project_profiles"
    MODEL_PROFILES = "model_profiles"
    WORKFLOW_TASKS = "workflow_tasks"
    REPORT_RUNS = "report_runs"
    RUN_EVENTS = "run_events"
    RUN_ARTIFACTS = "run_artifacts"
    EVIDENCE_ITEMS = "evidence_items"
    CHANGE_CLASSIFICATIONS = "change_classifications"
    SCREENSHOTS = "screenshots"
    EVALUATION_EXPERIMENTS = "evaluation_experiments"
    EVALUATION_RUNS = "evaluation_runs"
    EVALUATION_COMPARISONS = "evaluation_comparisons"
    KNOWLEDGE_INDEX_RUNS = "knowledge_index_runs"
    KNOWLEDGE_NODES = "knowledge_nodes"
    KNOWLEDGE_EDGES = "knowledge_edges"
    KNOWLEDGE_CHUNKS = "knowledge_chunks"
    KNOWLEDGE_ANNOTATION_RUNS = "knowledge_annotation_runs"
    KNOWLEDGE_ANNOTATIONS = "knowledge_annotations"
    KNOWLEDGE_CONCEPTS = "knowledge_concepts"
    KNOWLEDGE_ANNOTATION_EDGES = "knowledge_annotation_edges"
    LLM_CONVERSATIONS = "llm_conversations"
    LLM_CONVERSATION_EVENTS = "llm_conversation_events"
    MODEL_CALL_LEDGER = "model_call_ledger"


class ProjectCleanupRequest(BaseModel):
    target_project_ids: list[str] = Field(min_length=1)
    protected_project_ids: list[str] = Field(min_length=1)

    @field_validator("target_project_ids", "protected_project_ids")
    @classmethod
    def normalize_project_ids(cls, value: list[str]) -> list[str]:
        normalized = sorted({project_id.strip() for project_id in value if project_id.strip()})
        if not normalized:
            raise ValueError("At least one non-empty project id is required.")
        return normalized

    @model_validator(mode="after")
    def reject_protected_targets(self) -> ProjectCleanupRequest:
        overlap = sorted(set(self.target_project_ids) & set(self.protected_project_ids))
        if overlap:
            raise ValueError("Protected projects cannot be cleanup targets: " + ", ".join(overlap))
        return self


class ProjectCleanupResourceCount(BaseModel):
    resource: ProjectCleanupResource
    count: int = Field(ge=0)


class ProjectCleanupArtifact(BaseModel):
    id: str
    run_id: str
    artifact_type: str
    uri: str


class ProjectCleanupRepositoryCache(BaseModel):
    repository_id: str
    path: str
    shared_project_ids: list[str] = Field(default_factory=list)
    deletable: bool = False


class ProjectCleanupProject(BaseModel):
    project_id: str
    name: str | None = None
    state: ProjectCleanupState
    run_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)
    artifacts: list[ProjectCleanupArtifact] = Field(default_factory=list)
    s3_keys: list[str] = Field(default_factory=list)
    repository_caches: list[ProjectCleanupRepositoryCache] = Field(default_factory=list)
    active_run_ids: list[str] = Field(default_factory=list)
    active_workflow_task_ids: list[str] = Field(default_factory=list)
    resource_counts: list[ProjectCleanupResourceCount] = Field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.active_run_ids or self.active_workflow_task_ids)


class ProjectCleanupPlan(BaseModel):
    schema_version: str = "1.0"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    artifact_bucket: str
    artifact_endpoint_url: str | None = None
    artifact_prefix: str
    repository_cache_root: str
    target_project_ids: list[str]
    protected_project_ids: list[str]
    projects: list[ProjectCleanupProject]
    checksum: str = ""

    @property
    def safe_to_apply(self) -> bool:
        return not any(project.blocked for project in self.projects)


class ProjectCleanupApplyResult(BaseModel):
    plan_checksum: str
    deleted_project_ids: list[str] = Field(default_factory=list)
    already_absent_project_ids: list[str] = Field(default_factory=list)
    database_counts: list[ProjectCleanupResourceCount] = Field(default_factory=list)
    deleted_s3_keys: list[str] = Field(default_factory=list)
    deleted_repository_cache_paths: list[str] = Field(default_factory=list)
    external_errors: list[str] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.external_errors
