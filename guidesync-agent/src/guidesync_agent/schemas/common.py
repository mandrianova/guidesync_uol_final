from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import SecretStr


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


class TaskInterfaceAuthCookieMode(StrEnum):
    INHERIT = "inherit"
    OVERRIDE = "override"
    DISABLED = "disabled"


class TaskInterfaceAuthCookieUpdate(StrEnum):
    KEEP = "keep"
    REPLACE = "replace"
    REMOVE = "remove"


def normalize_task_interface_auth_cookie(
    value: SecretStr | str | None,
) -> SecretStr | None:
    if value is None:
        return None
    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
    raw = raw.strip()
    if not raw:
        return None
    if len(raw) > 8_192:
        raise ValueError("UI authentication cookie must not exceed 8192 characters.")
    if "\n" in raw or "\r" in raw:
        raise ValueError("UI authentication cookie must be a single Cookie header value.")
    pairs = [pair.strip() for pair in raw.split(";") if pair.strip()]
    if not pairs or any("=" not in pair or not pair.split("=", 1)[0].strip() for pair in pairs):
        raise ValueError("UI authentication cookie must contain name=value pairs.")
    return SecretStr(raw)


class VideoPresentationPolicy(StrEnum):
    DISABLED = "disabled"
    OPTIONAL = "optional"
    REQUIRED = "required"


class ReportLocale(StrEnum):
    ENGLISH = "en"
    RUSSIAN = "ru"


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
    CANCELLED = "cancelled"


class SemanticRankerMode(StrEnum):
    EMBEDDING_ENDPOINT = "embedding_endpoint"
    SENTENCE_TRANSFORMERS = "sentence_transformers"
    DETERMINISTIC_TEST = "deterministic_test"


ThinkingSetting = bool | Literal["minimal", "low", "medium", "high", "xhigh"]
