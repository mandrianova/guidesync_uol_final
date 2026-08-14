from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from guidesync_agent.schemas import (
    DocumentationInput,
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProjectConfig,
    ProjectProfileStatus,
    ProjectRepository,
    ProjectRunRequest,
    ProviderConfig,
    ReportConfig,
    RepositoryInput,
    RunMode,
    ScreenshotPolicy,
    TaskInterfaceAuthMode,
)
from guidesync_agent.schemas.model_roles import ModelRole
from guidesync_agent.services.model_roles import provider_config_for_role
from guidesync_agent.services.project_profile.service import latest_project_profile
from guidesync_agent.storage import effective_model_configuration_from_provider_config


@dataclass(frozen=True)
class RepositoryRunSelection:
    name: str
    ref: str
    branch: str | None = None


def workflow_planning_run_result(request: GuideSyncRunRequest) -> GuideSyncRunResult:
    return GuideSyncRunResult(
        run_id=request.run_id,
        # Project runs are owned by the durable workflow queue. Keeping this
        # staging state distinct from `queued` prevents the generic run worker
        # from claiming the run before its workflow task has been enqueued.
        status="planning",
        request=request,
        evidence=EvidenceBundle(),
        findings=[],
    )


def build_project_run_request(
    *,
    project: ProjectConfig,
    request: ProjectRunRequest,
) -> GuideSyncRunRequest:
    run_id = f"{project.id}-{uuid4().hex[:8]}"
    repositories = project_run_repositories(project, request)
    documentation = [
        DocumentationInput(
            name=document.name,
            path=Path(document.path) if document.path else None,
            description=document.description,
        )
        for document in project.documentation
        if document.path
    ]
    provider = provider_for_run()
    effective_model_configuration = effective_model_configuration_from_provider_config(provider)
    project_profile = latest_project_profile(project.id)
    task_interface_url = (
        (request.task_interface_url or "").strip()
        or (project.task_interface_url or "").strip()
        or None
    )
    screenshot_policy = (
        ScreenshotPolicy.OPTIONAL if task_interface_url else ScreenshotPolicy.DISABLED
    )
    auth_mode = request.task_interface_auth_mode
    auth_type = None
    auth_secret = None
    if task_interface_url:
        if auth_mode is TaskInterfaceAuthMode.OVERRIDE:
            auth_type = request.task_interface_auth_type
            auth_secret = request.task_interface_auth_secret
        elif auth_mode is TaskInterfaceAuthMode.INHERIT and task_interface_origins_match(
            task_interface_url,
            project.task_interface_url,
        ):
            auth_type = project.task_interface_auth_type
            auth_secret = project.task_interface_auth_secret
        if auth_secret is None:
            auth_mode = TaskInterfaceAuthMode.DISABLED
    else:
        auth_mode = TaskInterfaceAuthMode.DISABLED
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
            product_name=project.name,
            title=f"{project.name} release notes",
            locale=request.report_locale,
            formats=["md", "json"],
        ),
        task_interface_url=task_interface_url,
        task_interface_auth_mode=auth_mode,
        task_interface_auth_type=auth_type,
        has_task_interface_auth=auth_secret is not None,
        task_interface_auth_secret=auth_secret,
        screenshot_policy=screenshot_policy,
        effective_model_configuration=effective_model_configuration,
        project_profile_snapshot_id=project_profile_snapshot_id,
        evaluation_notes=(
            f"Run launched from saved project config at "
            f"{datetime.now(UTC).isoformat()} with branch and period filters."
        ),
    )


def task_interface_origins_match(first: str | None, second: str | None) -> bool:
    if not first or not second:
        return False
    try:
        first_url = urlsplit(first)
        second_url = urlsplit(second)
        return (
            first_url.scheme.casefold(),
            first_url.hostname,
            effective_port(first_url.scheme, first_url.port),
        ) == (
            second_url.scheme.casefold(),
            second_url.hostname,
            effective_port(second_url.scheme, second_url.port),
        )
    except ValueError:
        return False


def effective_port(scheme: str, port: int | None) -> int | None:
    if port is not None:
        return port
    return {"http": 80, "https": 443}.get(scheme.casefold())


def build_retry_run_request(previous: GuideSyncRunResult) -> GuideSyncRunRequest:
    run_id = f"{project_id_for_run(previous.request)}-{uuid4().hex[:8]}"
    provider = provider_for_run()
    return previous.request.model_copy(
        update={
            "run_id": run_id,
            "retry_of_run_id": previous.run_id,
            "provider": provider,
            "effective_model_configuration": (
                effective_model_configuration_from_provider_config(provider)
            ),
            "report": previous.request.report.model_copy(
                update={"output_dir": Path(f"outputs/{run_id}")}
            ),
            "evaluation_notes": (
                f"Retry of {previous.run_id} launched at {datetime.now(UTC).isoformat()}."
            ),
        }
    )


def project_id_for_run(request: GuideSyncRunRequest) -> str:
    project_ids = {
        repository.project_id
        for repository in request.repositories
        if repository.project_id is not None
    }
    if len(project_ids) != 1:
        raise ValueError("Only report runs from one saved project can be retried.")
    return project_ids.pop()


def project_run_repositories(
    project: ProjectConfig,
    request: ProjectRunRequest,
) -> list[RepositoryInput]:
    inputs: list[RepositoryInput] = []
    for repository in project.repositories:
        default_branch = repository.default_branch or "HEAD"
        if request.mode == RunMode.SELECT_BRANCHES:
            for branch in request.branches.get(repository.id, []):
                inputs.append(
                    repository_run_input(
                        project,
                        repository,
                        request,
                        RepositoryRunSelection(
                            name=f"{repository.name} [{branch}]",
                            ref=default_branch,
                            branch=branch,
                        ),
                    )
                )
            continue
        inputs.append(
            repository_run_input(
                project,
                repository,
                request,
                RepositoryRunSelection(
                    name=repository.name,
                    ref=default_branch,
                    branch=default_branch if default_branch != "HEAD" else None,
                ),
            )
        )
    return inputs


def repository_run_input(
    project: ProjectConfig,
    repository: ProjectRepository,
    request: ProjectRunRequest,
    selection: RepositoryRunSelection,
) -> RepositoryInput:
    period_mode = request.mode == RunMode.DEFAULT_BRANCH_PERIOD
    return RepositoryInput(
        name=selection.name,
        project_id=project.id,
        repository_id=repository.id,
        local_path=Path(repository.local_path) if repository.local_path else None,
        url=repository.url,
        ref=selection.ref,
        since=request.since if period_mode else None,
        until=request.until if period_mode else None,
        branches=[selection.branch] if selection.branch else [],
        paths=repository.analysis_paths,
        max_commits=request.max_commits,
    )


def provider_for_run() -> ProviderConfig:
    return provider_config_for_role(ModelRole.ORCHESTRATOR)
