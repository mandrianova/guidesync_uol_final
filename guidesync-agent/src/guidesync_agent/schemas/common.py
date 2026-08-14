from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal

from pydantic import SecretStr

from guidesync_agent.browser_auth import TaskInterfaceAuthType


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


class TaskInterfaceAuthMode(StrEnum):
    INHERIT = "inherit"
    OVERRIDE = "override"
    DISABLED = "disabled"


class TaskInterfaceAuthUpdate(StrEnum):
    KEEP = "keep"
    REPLACE = "replace"
    REMOVE = "remove"


def normalize_task_interface_auth_secret(
    value: SecretStr | str | None,
    auth_type: TaskInterfaceAuthType,
) -> SecretStr | None:
    if value is None:
        return None
    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
    raw = raw.strip()
    if not raw:
        return None
    if auth_type is TaskInterfaceAuthType.COOKIE:
        return normalize_task_interface_cookie(raw)
    return normalize_task_interface_local_storage(raw)


def normalize_task_interface_cookie(raw: str) -> SecretStr:
    if len(raw) > 8_192:
        raise ValueError("UI authentication cookie must not exceed 8192 characters.")
    if "\n" in raw or "\r" in raw:
        raise ValueError("UI authentication cookie must be a single Cookie header value.")
    pairs = [pair.strip() for pair in raw.split(";") if pair.strip()]
    if not pairs or any(
        "=" not in pair or not pair.split("=", 1)[0].strip() for pair in pairs
    ):
        raise ValueError("UI authentication cookie must contain name=value pairs.")
    return SecretStr(raw)


def normalize_task_interface_local_storage(raw: str) -> SecretStr:
    if len(raw) > 65_536:
        raise ValueError("UI localStorage JSON must not exceed 65536 characters.")
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("UI localStorage authorization must be a JSON object.") from exc
    if not isinstance(entries, dict) or not entries or len(entries) > 64:
        raise ValueError("UI localStorage authorization must contain 1 to 64 entries.")
    normalized: dict[str, str] = {}
    for key, entry_value in entries.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 512:
            raise ValueError("UI localStorage keys must be non-empty strings up to 512 characters.")
        if not isinstance(entry_value, str) or len(entry_value) > 32_768:
            raise ValueError("UI localStorage values must be strings up to 32768 characters.")
        normalized[key] = entry_value
    return SecretStr(json.dumps(normalized, sort_keys=True, separators=(",", ":")))


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
