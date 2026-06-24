from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from guidesync_agent.config import public_runtime_config

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
templates = Environment(
    loader=FileSystemLoader(PACKAGE_ROOT / "templates"),
    autoescape=select_autoescape(("html", "xml")),
)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    template = templates.get_template("index.html")
    return HTMLResponse(template.render())


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "guidesync-agent"}


@router.get("/config")
async def runtime_config() -> dict[str, str | None]:
    return public_runtime_config()
