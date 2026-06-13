from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from guidesync_agent.agent import run_guidesync, save_run_state
from guidesync_agent.auth import basic_auth_response, request_is_authorized
from guidesync_agent.config import provider_config_from_env, public_runtime_config
from guidesync_agent.evidence import list_github_branches
from guidesync_agent.schemas import (
    DocumentationInput,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProjectConfig,
    ProjectCreate,
    ProjectRunRequest,
    ReportConfig,
    RepositoryInput,
    RunMode,
    RunSummary,
)
from guidesync_agent.storage import create_project_store, create_run_store, initialize_storage

PACKAGE_ROOT = Path(__file__).resolve().parent
templates = Environment(
    loader=FileSystemLoader(PACKAGE_ROOT / "templates"),
    autoescape=select_autoescape(("html", "xml")),
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
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
    run_id = f"{project_id}-{uuid4().hex[:8]}"
    repositories = [
        RepositoryInput(
            name=repository.name,
            url=repository.url,
            since=request.since if request.mode == RunMode.DEFAULT_BRANCH_PERIOD else None,
            until=request.until if request.mode == RunMode.DEFAULT_BRANCH_PERIOD else None,
            branches=(
                request.branches.get(repository.id, [])
                if request.mode == RunMode.SELECT_BRANCHES
                else ([repository.default_branch] if repository.default_branch else [])
            ),
            paths=repository.paths,
        )
        for repository in project.repositories
    ]
    documentation = [
        DocumentationInput(
            name=document.name,
            description=document.description,
            content=document.content,
        )
        for document in project.documentation
    ]
    run_request = GuideSyncRunRequest(
        run_id=run_id,
        goal=request.goal,
        audience=request.audience,
        provider=provider_config_from_env(request.provider),
        repositories=repositories,
        documentation=documentation,
        report=ReportConfig(
            output_dir=Path(f"outputs/{run_id}"),
            title=f"{project.name} analysis report",
            formats=["html", "md", "json"],
        ),
        evaluation_notes=(
            f"Run launched from saved project config at "
            f"{datetime.now(UTC).isoformat()} with branch and period filters."
        ),
    )
    save_run_state(run_request, "queued")
    summaries = create_run_store().list_runs(project_id=project_id)
    return next(summary for summary in summaries if summary.run_id == run_id)


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> GuideSyncRunResult:
    result = create_run_store().get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the GuideSync Agent FastAPI app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8770, type=int)
    args = parser.parse_args()
    uvicorn.run("guidesync_agent.api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
