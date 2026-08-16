from __future__ import annotations

from guidesync_agent.schemas import GuideSyncRunRequest, ProviderConfig
from guidesync_agent.settings import get_settings
from guidesync_agent.storage import create_model_settings_store


def rehydrate_provider_credentials(config: ProviderConfig) -> ProviderConfig:
    profile_id = config.metadata.get("model_profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        return config
    profile = next(
        (
            item
            for item in create_model_settings_store().list_profiles()
            if item.id == profile_id
        ),
        None,
    )
    if profile is None:
        raise RuntimeError(f"Saved model profile is unavailable: {profile_id}")
    return config.model_copy(update={"api_key": profile.api_key})


def with_run_provider_settings(
    config: ProviderConfig,
    request: GuideSyncRunRequest,
) -> ProviderConfig:
    browser = config.browser or get_settings().browser.tool_settings()
    browser = browser.model_copy(
        update={
            "base_url": request.task_interface_url or browser.base_url,
            "screenshot_dir": request.report.output_dir / "screenshots",
            "auth_type": request.task_interface_auth_type,
            "auth_secret": request.task_interface_auth_secret,
        }
    )
    return config.model_copy(update={"browser": browser})
