from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from guidesync_agent.schemas import (
    DocumentationInput,
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProjectConfig,
    ProjectRunRequest,
    ProviderConfig,
    ReportConfig,
    RepositoryInput,
    RunMode,
    RunSummary,
)
from guidesync_agent.storage import RunStore, create_model_settings_store


class ReportRunService:
    def __init__(self, run_store: RunStore) -> None:
        self.run_store = run_store

    def create_project_run(
        self,
        *,
        project: ProjectConfig,
        request: ProjectRunRequest,
    ) -> RunSummary:
        run_request = self.build_project_run_request(project=project, request=request)
        self.run_store.save(
            GuideSyncRunResult(
                run_id=run_request.run_id,
                status="queued",
                request=run_request,
                evidence=EvidenceBundle(),
                findings=[],
            )
        )
        self.run_store.record_run_event(run_request.run_id, "queued", "Run created.", "api")
        summaries = self.run_store.list_runs(project_id=project.id)
        return next(summary for summary in summaries if summary.run_id == run_request.run_id)

    def build_project_run_request(
        self,
        *,
        project: ProjectConfig,
        request: ProjectRunRequest,
    ) -> GuideSyncRunRequest:
        run_id = f"{project.id}-{uuid4().hex[:8]}"
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
        return GuideSyncRunRequest(
            run_id=run_id,
            goal=request.goal,
            audience=request.audience,
            provider=self.provider_for_run(request),
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

    @staticmethod
    def provider_for_run(request: ProjectRunRequest) -> ProviderConfig:
        return request.provider or create_model_settings_store().provider_config()
