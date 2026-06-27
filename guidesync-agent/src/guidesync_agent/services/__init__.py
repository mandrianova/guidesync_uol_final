from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from guidesync_agent.schemas import (
    DocumentationInput,
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ModelSettings,
    ProjectConfig,
    ProjectProfileStatus,
    ProjectRunRequest,
    ProviderConfig,
    ReportConfig,
    RepositoryInput,
    RunMode,
    RunSummary,
)
from guidesync_agent.services.project_profile import latest_project_profile
from guidesync_agent.storage import (
    RunStore,
    create_model_settings_store,
    effective_model_configuration_from_provider_config,
    model_settings_to_provider_config,
)


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

    def blocked_run_result(self, request: GuideSyncRunRequest) -> GuideSyncRunResult:
        return GuideSyncRunResult(
            run_id=request.run_id,
            status="blocked",
            request=request,
            evidence=EvidenceBundle(),
            findings=[],
        )

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
                project_id=project.id,
                repository_id=repository.id,
                local_path=Path(repository.local_path) if repository.local_path else None,
                url=repository.url,
                since=request.since if request.mode == RunMode.DEFAULT_BRANCH_PERIOD else None,
                until=request.until if request.mode == RunMode.DEFAULT_BRANCH_PERIOD else None,
                branches=(
                    request.branches.get(repository.id, [])
                    if request.mode == RunMode.SELECT_BRANCHES
                    else ([repository.default_branch] if repository.default_branch else [])
                ),
                paths=repository.analysis_paths,
            )
            for repository in project.repositories
        ]
        documentation = [
            DocumentationInput(
                name=document.name,
                path=Path(document.path) if document.path else None,
                description=document.description,
            )
            for document in project.documentation
            if document.path
        ]
        provider = self.provider_for_run(request)
        effective_model_configuration = effective_model_configuration_from_provider_config(provider)
        project_profile = latest_project_profile(project.id)
        project_profile_snapshot_id = request.project_profile_snapshot_id
        if project_profile_snapshot_id is None and project_profile is not None:
            if project_profile.status == ProjectProfileStatus.COMPLETED:
                project_profile_snapshot_id = project_profile.id
        return GuideSyncRunRequest(
            run_id=run_id,
            goal=request.goal,
            audience=request.audience or project.audience,
            provider=provider,
            repositories=repositories,
            documentation=documentation,
            report=ReportConfig(
                output_dir=Path(f"outputs/{run_id}"),
                title=f"{project.name} release notes",
                formats=["html", "md", "json"],
            ),
            task_interface_url=request.task_interface_url,
            screenshot_policy=request.screenshot_policy,
            requested_model_settings=request.requested_model_settings,
            effective_model_configuration=effective_model_configuration,
            project_profile_snapshot_id=project_profile_snapshot_id,
            evaluation_notes=(
                f"Run launched from saved project config at "
                f"{datetime.now(UTC).isoformat()} with branch and period filters."
            ),
        )

    @staticmethod
    def provider_for_run(request: ProjectRunRequest) -> ProviderConfig:
        provider = request.provider or provider_from_requested_settings(request)
        settings = request.requested_model_settings
        if settings is None:
            return provider
        update: dict[str, object] = {}
        if settings.provider is not None:
            update["provider"] = settings.provider
        if settings.model is not None:
            update["model"] = settings.model
        if settings.base_url is not None:
            update["base_url"] = settings.base_url
        if settings.timeout_seconds is not None:
            update["timeout_seconds"] = settings.timeout_seconds
        if settings.thinking is not None:
            update["thinking"] = settings.thinking
        if settings.model_profile_id is not None:
            update["metadata"] = {
                **provider.metadata,
                "model_profile_id": settings.model_profile_id,
            }
        if not update:
            return provider
        return provider.model_copy(update=update)


def provider_from_requested_settings(request: ProjectRunRequest) -> ProviderConfig:
    settings_store = create_model_settings_store()
    model_settings = settings_store.get()
    requested = request.requested_model_settings
    if requested and requested.model_profile_id:
        model_settings = model_settings_by_id(
            settings_store.list_profiles(),
            requested.model_profile_id,
        )
    return model_settings_to_provider_config(model_settings)


def model_settings_by_id(profiles: list[ModelSettings], profile_id: str) -> ModelSettings:
    return next((profile for profile in profiles if profile.id == profile_id), profiles[0])
