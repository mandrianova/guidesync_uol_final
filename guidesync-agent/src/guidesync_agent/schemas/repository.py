from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RepositoryBranch(BaseModel):
    name: str
    updated_at: str | None = None


class BranchListResponse(BaseModel):
    branches: list[RepositoryBranch] = Field(default_factory=list)
    warning: str | None = None


class RepositorySyncTask(BaseModel):
    task_type: Literal["repository_sync"] = "repository_sync"
    project_id: str
    repository_id: str


class ProjectProfileTask(BaseModel):
    task_type: Literal["project_profile"] = "project_profile"
    project_id: str
    profile_id: str | None = None
    reason: str = "project_changed"


class RepositoryInput(BaseModel):
    name: str
    project_id: str | None = None
    repository_id: str | None = None
    path: Path | None = None
    local_path: Path | None = None
    url: str | None = None
    ref: str = "HEAD"
    since: str | None = "30 days ago"
    until: str | None = None
    branches: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    max_commits: int | None = Field(default=None, ge=1)

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class DocumentationInput(BaseModel):
    name: str
    path: Path | None = None
    description: str | None = None
    content: str | None = None
