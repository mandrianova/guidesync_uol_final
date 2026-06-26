from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .provider import ProviderConfig
from .run import GuideSyncRunRequest, ValidationFinding


class BenchmarkCase(BaseModel):
    id: str
    name: str
    request: GuideSyncRunRequest


class BenchmarkSuite(BaseModel):
    name: str
    providers: list[ProviderConfig]
    cases: list[BenchmarkCase]


class BenchmarkScore(BaseModel):
    factuality: int = Field(ge=0, le=3)
    evidence_use: int = Field(ge=0, le=3)
    documentation_usefulness: int = Field(ge=0, le=3)
    traceability: int = Field(ge=0, le=3)
    reviewer_effort: int = Field(ge=0, le=3)


class BenchmarkResult(BaseModel):
    suite: str
    case_id: str
    provider: str
    model: str
    run_id: str
    status: str
    score: BenchmarkScore
    findings: list[ValidationFinding] = Field(default_factory=list)
    latency_ms: int | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)


class ModelComparisonRequest(BaseModel):
    name: str
    base_request: GuideSyncRunRequest
    providers: list[ProviderConfig]
    input_bundle_id: str | None = None
    rubric_version: str = "model-comparison-rubric-v1"


class ModelComparisonRun(BaseModel):
    input_bundle_id: str
    provider: str
    model: str
    run_id: str
    status: str
    score: BenchmarkScore
    latency_ms: int | None = None
    cost: dict[str, Any] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    findings_count: int = 0
    artifacts: dict[str, str] = Field(default_factory=dict)


class ModelComparisonReport(BaseModel):
    id: str = Field(default_factory=lambda: f"comparison-{uuid4().hex[:10]}")
    name: str
    input_bundle_id: str
    rubric_version: str
    runs: list[ModelComparisonRun]
    recommendation: str
    artifacts: dict[str, str] = Field(default_factory=dict)
