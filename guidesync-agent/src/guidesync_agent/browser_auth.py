from __future__ import annotations

from enum import StrEnum


class TaskInterfaceAuthType(StrEnum):
    LOCAL_STORAGE = "local_storage"
    COOKIE = "cookie"
