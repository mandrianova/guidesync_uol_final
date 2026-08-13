from __future__ import annotations

from guidesync_agent.schemas import GuideSyncRunRequest, ProviderConfig
from guidesync_agent.settings import get_settings
from guidesync_agent.storage import GLOBAL_MODEL_PROFILE_ID, create_model_settings_store


def rehydrate_global_provider(config: ProviderConfig) -> ProviderConfig:
    if config.metadata.get("model_profile_id") != GLOBAL_MODEL_PROFILE_ID:
        return config
    stored = create_model_settings_store().provider_config()
    return stored.model_copy(
        update={
            "provider": config.provider,
            "model": config.model,
            "base_url": config.base_url,
            "timeout_seconds": config.timeout_seconds,
            "max_concurrent_agents": config.max_concurrent_agents,
            "thinking": config.thinking,
            "browser": config.browser,
            "metadata": config.metadata,
        }
    )


def with_run_provider_settings(
    config: ProviderConfig,
    request: GuideSyncRunRequest,
) -> ProviderConfig:
    browser = config.browser or get_settings().browser.tool_settings()
    browser = browser.model_copy(
        update={
            "base_url": request.task_interface_url or browser.base_url,
            "screenshot_dir": request.report.output_dir / "screenshots",
            "auth_cookie": request.task_interface_auth_cookie,
        }
    )
    return config.model_copy(update={"browser": browser})
