from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .knowledge import KnowledgeEdge, KnowledgeNode, KnowledgeNodeKind, KnowledgeSearchResult
from .run import ValidationFinding


class ToolPagination(BaseModel):
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    total: int = Field(ge=0)
    next_offset: int | None = None
    truncated: bool = False


class ToolError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ToolValidationFinding(BaseModel):
    severity: str
    check: str
    message: str
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)


class RepositoryFileWindow(BaseModel):
    ok: bool = True
    repository_id: str
    path: str
    content: str = ""
    pagination: ToolPagination
    artifact_ref: str | None = None
    error: ToolError | None = None


class RepositoryDiffWindow(BaseModel):
    ok: bool = True
    repository_id: str
    path: str | None = None
    base_ref: str | None = None
    head_ref: str
    diff: str = ""
    pagination: ToolPagination
    artifact_ref: str | None = None
    error: ToolError | None = None


class RepositorySearchMatch(BaseModel):
    repository_id: str
    path: str
    line_number: int
    preview: str


class RepositorySearchResult(BaseModel):
    ok: bool = True
    query: str
    matches: list[RepositorySearchMatch] = Field(default_factory=list)
    total: int = 0
    truncated: bool = False
    error: ToolError | None = None


class ChangedFileRef(BaseModel):
    path: str
    status: str


class ChangedFilesResult(BaseModel):
    ok: bool = True
    repository_id: str
    base_ref: str | None = None
    head_ref: str
    files: list[ChangedFileRef] = Field(default_factory=list)
    error: ToolError | None = None


class KnowledgeDocumentWindow(BaseModel):
    ok: bool = True
    document_id: str
    path: str
    content: str = ""
    pagination: ToolPagination
    artifact_ref: str | None = None
    error: ToolError | None = None


class ContextChunk(BaseModel):
    id: str
    role: str = "context"
    text: str
    retain: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextSummaryArtifact(BaseModel):
    id: str = Field(default_factory=lambda: f"context-summary-{uuid4().hex[:10]}")
    path: str
    prompt_version: str
    original_chunk_ids: list[str] = Field(default_factory=list)
    summary_chunk_id: str
    original_token_estimate: int = 0
    summary_token_estimate: int = 0
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ContextBudgetResult(BaseModel):
    chunks: list[ContextChunk]
    artifact: ContextSummaryArtifact | None = None
    findings: list[ValidationFinding] = Field(default_factory=list)
    token_estimate: int = 0


class FileChangeSummary(BaseModel):
    id: str = Field(default_factory=lambda: f"file-summary-{uuid4().hex[:10]}")
    repository_id: str
    path: str
    status: str
    technical_summary: str
    product_impact: str
    documentation_keywords: list[str] = Field(default_factory=list)
    docs_to_search: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    needs_main_agent_review: bool = False
    artifact_uri: str | None = None


class KnowledgeContextPackRequest(BaseModel):
    goal: str = Field(min_length=1)
    project_id: str | None = None
    kinds: list[KnowledgeNodeKind] = Field(default_factory=list)
    path_prefixes: list[str] = Field(default_factory=list)
    taxonomy_version: str | None = None
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    keyphrases: list[str] = Field(default_factory=list)
    extracted_names: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    documentation_areas: list[str] = Field(default_factory=list)
    token_budget: int = Field(default=1_500, ge=200, le=20_000)
    limit: int = Field(default=8, ge=1, le=30)


class KnowledgeContextPack(BaseModel):
    goal: str
    results: list[KnowledgeSearchResult]
    nodes: list[KnowledgeNode]
    edges: list[KnowledgeEdge]
    warnings: list[str] = Field(default_factory=list)
