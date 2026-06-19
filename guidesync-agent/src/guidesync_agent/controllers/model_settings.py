from __future__ import annotations

from guidesync_agent.schemas import ModelSettings, ModelSettingsUpdate
from guidesync_agent.storage import GLOBAL_MODEL_PROFILE_ID, create_model_settings_store


class ReadOnlyModelProfileError(ValueError):
    """Raised when a caller tries to mutate the built-in model profile."""


class ModelProfileDeleteError(ValueError):
    """Raised when a model profile cannot be deleted."""


def get_model_settings() -> ModelSettings:
    return create_model_settings_store().get()


def update_model_settings(settings: ModelSettingsUpdate) -> ModelSettings:
    store = create_model_settings_store()
    if store.get().id == GLOBAL_MODEL_PROFILE_ID:
        raise ReadOnlyModelProfileError("Built-in default model cannot be edited.")
    return store.save(settings)


def list_model_profiles() -> list[ModelSettings]:
    return create_model_settings_store().list_profiles()


def create_model_profile(settings: ModelSettingsUpdate) -> ModelSettings:
    return create_model_settings_store().save_profile(settings)


def update_model_profile(profile_id: str, settings: ModelSettingsUpdate) -> ModelSettings:
    if profile_id == GLOBAL_MODEL_PROFILE_ID:
        raise ReadOnlyModelProfileError("Built-in default model cannot be edited.")
    return create_model_settings_store().save_profile(settings, profile_id=profile_id)


def set_default_model_profile(profile_id: str) -> ModelSettings | None:
    return create_model_settings_store().set_default(profile_id)


def delete_model_profile(profile_id: str) -> ModelSettings:
    if profile_id == GLOBAL_MODEL_PROFILE_ID:
        raise ReadOnlyModelProfileError("Built-in default model cannot be deleted.")
    default_profile = create_model_settings_store().delete_profile(profile_id)
    if default_profile is None:
        raise ModelProfileDeleteError("Model profile was not found or cannot be deleted.")
    return default_profile

