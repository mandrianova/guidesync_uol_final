from __future__ import annotations

import os

GLOBAL_MODEL_PROFILE_ID = "global-default"


class StorageConfigurationError(RuntimeError):
    pass


def database_url() -> str:
    if os.environ.get("GUIDESYNC_STORAGE_MODE") is not None:
        raise StorageConfigurationError(
            "GUIDESYNC_STORAGE_MODE is no longer supported; GuideSync storage is database-only."
        )
    configured = os.environ.get("GUIDESYNC_DATABASE_URL")
    if not configured:
        raise StorageConfigurationError(
            "GUIDESYNC_DATABASE_URL is required because GuideSync storage is database-only. "
            "Run GuideSync through Docker Compose or configure a database URL for tests."
        )
    return configured
