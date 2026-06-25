from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from guidesync_agent.config import public_runtime_config

router = APIRouter()


@router.get("/", include_in_schema=False)
async def home() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "guidesync-agent"}


@router.get("/config")
async def runtime_config() -> dict[str, str | None]:
    return public_runtime_config()
