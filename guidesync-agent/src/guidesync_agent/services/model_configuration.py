from __future__ import annotations

from guidesync_agent.schemas import GuideSyncRunRequest, ProviderConfig
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
            "thinking": config.thinking,
            "metadata": config.metadata,
        }
    )


def with_run_provider_metadata(
    config: ProviderConfig,
    request: GuideSyncRunRequest,
) -> ProviderConfig:
    metadata = {
        **config.metadata,
        "screenshot_dir": str(request.report.output_dir / "screenshots"),
    }
    return config.model_copy(update={"metadata": metadata})
