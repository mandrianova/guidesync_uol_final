from __future__ import annotations

from guidesync_agent.settings import get_settings

GLOBAL_MODEL_PROFILE_ID = "global-default"


class StorageConfigurationError(RuntimeError):
    pass


def database_url() -> str:
    settings = get_settings().storage
    if settings.legacy_mode is not None:
        raise StorageConfigurationError(
            "GUIDESYNC_STORAGE_MODE is no longer supported; GuideSync storage is database-only."
        )
    configured = settings.database_url
    if not configured:
        raise StorageConfigurationError(
            "GUIDESYNC_DATABASE_URL is required because GuideSync storage is database-only. "
            "Run GuideSync through Docker Compose or configure a database URL for tests."
        )
    return configured
