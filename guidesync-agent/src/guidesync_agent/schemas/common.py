from __future__ import annotations

from enum import StrEnum
from typing import Literal


class ProviderKind(StrEnum):
    MOCK = "mock"
    PYDANTIC_AI = "pydantic_ai"
    LOCAL_HTTP = "local_http"


class RunMode(StrEnum):
    DEFAULT_BRANCH_PERIOD = "default_branch_period"
    SELECT_BRANCHES = "select_branches"


class Audience(StrEnum):
    DEVELOPERS = "developers"
    END_USERS = "end_users"
    BUSINESS_ANALYSTS = "business_analysts"


class ScreenshotPolicy(StrEnum):
    DISABLED = "disabled"
    OPTIONAL = "optional"
    REQUIRED = "required"


class RepositoryCacheStatus(StrEnum):
    NOT_SYNCED = "not_synced"
    SYNCING = "syncing"
    READY = "ready"
    FAILED = "failed"


class ProjectProfileStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class StorageMode(StrEnum):
    DATABASE = "database"
    FILE = "file"


ThinkingSetting = bool | Literal["minimal", "low", "medium", "high", "xhigh"]
