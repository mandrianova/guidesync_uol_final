from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from guidesync_agent.agent import run_guidesync
from guidesync_agent.app_logging import configure_logging
from guidesync_agent.auth import basic_auth_response, request_is_authorized
from guidesync_agent.config import public_runtime_config
from guidesync_agent.evidence import list_github_branches
from guidesync_agent.reports import read_artifact, render_html
from guidesync_agent.schemas import (
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProjectConfig,
    ProjectCreate,
    ProjectRunRequest,
    RunSummary,
)
from guidesync_agent.services import ReportRunService
from guidesync_agent.storage import create_project_store, create_run_store, initialize_storage

PACKAGE_ROOT = Path(__file__).resolve().parent
templates = Environment(
    loader=FileSystemLoader(PACKAGE_ROOT / "templates"),
    autoescape=select_autoescape(("html", "xml")),
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    initialize_storage()
    yield


app = FastAPI(title="GuideSync Agent", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=PACKAGE_ROOT / "static"), name="static")


@app.middleware("http")
async def protect_deployed_app(request: Request, call_next):
    if request.url.path != "/health" and not request_is_authorized(request):
        return basic_auth_response()
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    template = templates.get_template("index.html")
    return HTMLResponse(template.render())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "guidesync-agent"}


@app.get("/config")
async def runtime_config() -> dict[str, str | None]:
    return public_runtime_config()


@app.get("/projects")
async def list_projects() -> list[ProjectConfig]:
    return create_project_store().list_projects()


@app.post("/projects")
async def create_project(project: ProjectCreate) -> ProjectConfig:
    return create_project_store().save(project)


@app.get("/projects/{project_id}")
async def get_project(project_id: str) -> ProjectConfig:
    project = create_project_store().get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return project


@app.put("/projects/{project_id}")
async def update_project(project_id: str, project: ProjectCreate) -> ProjectConfig:
    existing = create_project_store().get(project_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return create_project_store().save(project, project_id=project_id)


@app.get("/github/branches")
async def github_branches(url: str = Query(...)) -> dict[str, list[str] | str | None]:
    branches, warning = list_github_branches(url)
    return {"branches": branches, "warning": warning}


@app.post("/runs")
async def create_run(request: GuideSyncRunRequest) -> GuideSyncRunResult:
    return await run_guidesync(request)


@app.get("/runs")
async def list_runs(project_id: str | None = Query(default=None)) -> list[RunSummary]:
    return create_run_store().list_runs(project_id=project_id)


@app.get("/projects/{project_id}/runs")
async def list_project_runs(project_id: str) -> list[RunSummary]:
    project = create_project_store().get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return create_run_store().list_runs(project_id=project_id)


@app.post("/projects/{project_id}/runs")
async def create_project_run(
    project_id: str,
    request: ProjectRunRequest,
) -> RunSummary:
    project = create_project_store().get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return ReportRunService(create_run_store()).create_project_run(
        project=project,
        request=request,
    )


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> GuideSyncRunResult:
    result = create_run_store().get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return result


@app.get("/runs/{run_id}/artifacts/{filename}")
async def get_run_artifact(
    run_id: str,
    filename: str,
    print_view: bool = Query(default=False, alias="print"),
) -> Response:
    result = create_run_store().get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid artifact filename.")
    if filename == "report.html":
        body = render_html(result).encode("utf-8")
        if print_view:
            body = inject_print_script(body)
        return Response(
            content=body,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": 'inline; filename="report.html"'},
        )
    uri = result.artifacts.get(filename)
    if not uri:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {filename}")
    if uri.startswith(("http://", "https://")):
        return RedirectResponse(uri)
    try:
        artifact = read_artifact(uri)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Artifact file not found: {filename}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    body = artifact.body
    if print_view and filename.endswith(".html"):
        body = inject_print_script(body)
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    return Response(content=body, media_type=artifact.content_type, headers=headers)


def inject_print_script(body: bytes) -> bytes:
    html = body.decode("utf-8", errors="replace")
    script = "<script>window.addEventListener('load', () => window.print());</script>"
    if "</body>" in html:
        html = html.replace("</body>", f"{script}</body>")
    else:
        html += script
    return html.encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the GuideSync Agent FastAPI app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8770, type=int)
    args = parser.parse_args()
    uvicorn.run("guidesync_agent.api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
