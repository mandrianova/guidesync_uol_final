from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .evaluation_experiment import (
    AblationComparisonReport,
    EvaluationExperimentManifest,
    EvaluationExperimentRun,
)


class EvaluationExperimentCreate(BaseModel):
    manifest: EvaluationExperimentManifest


class EvaluationExperimentRecord(BaseModel):
    project_id: str
    manifest: EvaluationExperimentManifest
    manifest_checksum: str
    run_count: int = Field(default=0, ge=0)
    completed_run_count: int = Field(default=0, ge=0)
    failed_run_count: int = Field(default=0, ge=0)
    comparison_count: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class EvaluationExperimentPage(BaseModel):
    items: list[EvaluationExperimentRecord] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class EvaluationRunRecord(BaseModel):
    experiment_id: str
    run: EvaluationExperimentRun
    created_at: datetime
    updated_at: datetime


class EvaluationRunPage(BaseModel):
    items: list[EvaluationRunRecord] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class EvaluationComparisonRecord(BaseModel):
    id: str
    experiment_id: str
    report: AblationComparisonReport
    created_at: datetime
    updated_at: datetime


class EvaluationComparisonPage(BaseModel):
    items: list[EvaluationComparisonRecord] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
