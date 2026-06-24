from __future__ import annotations

from fastapi import APIRouter, HTTPException

from guidesync_agent.controllers import model_settings as controller
from guidesync_agent.schemas import ModelSettings, ModelSettingsUpdate

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("/model")
async def get_model_settings() -> ModelSettings:
    return controller.get_model_settings()


@router.put("/model")
async def update_model_settings(settings: ModelSettingsUpdate) -> ModelSettings:
    try:
        return controller.update_model_settings(settings)
    except controller.ReadOnlyModelProfileError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/models")
async def list_model_profiles() -> list[ModelSettings]:
    return controller.list_model_profiles()


@router.post("/models")
async def create_model_profile(settings: ModelSettingsUpdate) -> ModelSettings:
    return controller.create_model_profile(settings)


@router.put("/models/{profile_id}")
async def update_model_profile(profile_id: str, settings: ModelSettingsUpdate) -> ModelSettings:
    try:
        return controller.update_model_profile(profile_id, settings)
    except controller.ReadOnlyModelProfileError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.put("/models/{profile_id}/default")
async def set_default_model_profile(profile_id: str) -> ModelSettings:
    saved = controller.set_default_model_profile(profile_id)
    if saved is None:
        raise HTTPException(status_code=404, detail=f"Model profile not found: {profile_id}")
    return saved


@router.delete("/models/{profile_id}")
async def delete_model_profile(profile_id: str) -> ModelSettings:
    try:
        return controller.delete_model_profile(profile_id)
    except controller.ReadOnlyModelProfileError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except controller.ModelProfileDeleteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
