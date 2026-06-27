from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from guidesync_agent.schemas import (
    ProjectConfig,
    ProjectProfileAgentEvidence,
    ProjectProfileAgentOutput,
    ProjectProfileAgentRequest,
    ProjectProfileAgentResult,
    ProjectProfileBuildReason,
    ProjectProfileFileListing,
    ProjectProfileFileSelection,
    ProjectProfileRepositoryMapItem,
    ProjectProfileRepositorySummary,
    ProjectProfileSearchQuery,
    ProjectProfileSnapshot,
    ProjectProfileSourceRef,
    ProjectProfileToolBudget,
    ProjectProfileToolTraceRef,
    RepositorySearchResult,
    ValidationFinding,
)
from guidesync_agent.services.project_profile_fake_agent import FakeProjectProfileAgentProvider
from guidesync_agent.services.project_profile_local_provider import (
    LocalHTTPProjectProfileAgentProvider,
)
from guidesync_agent.tools.project_profile import (
    evidence_ref,
    list_repository_profile_files,
    list_repository_profile_files_from_root,
    read_repository_profile_file,
    search_repository_profile_files,
)


class ProjectProfileAgentProvider(Protocol):
    provider: str
    model: str

    def select_files(
        self,
        request: ProjectProfileAgentRequest,
        file_listings: list[ProjectProfileFileListing],
    ) -> object: ...

    def build_profile(
        self,
        request: ProjectProfileAgentRequest,
        evidence: ProjectProfileAgentEvidence,
        selection: ProjectProfileFileSelection,
    ) -> object: ...


class ProjectProfileAgentError(ValueError):
    def __init__(self, message: str, findings: list[ValidationFinding]) -> None:
        super().__init__(message)
        self.validation_findings = findings


@dataclass
class ProjectProfileRepositoryData:
    repository_map: ProjectProfileRepositoryMapItem
    source_ref: ProjectProfileSourceRef
    warnings: list[str]


def run_project_profile_agent(
    project: ProjectConfig,
    base_profile: ProjectProfileSnapshot,
    repository_data: list[ProjectProfileRepositoryData],
    *,
    provider: ProjectProfileAgentProvider | None = None,
    reason: str = "manual",
) -> ProjectProfileAgentResult:
    provider = provider or default_project_profile_agent_provider()
    started = time.perf_counter()
    request = build_agent_request(project, base_profile, repository_data, reason)
    file_listings = collect_file_listings(request)
    selection = ProjectProfileFileSelection.model_validate(
        provider.select_files(request, file_listings)
    )
    evidence = collect_agent_evidence(request, file_listings, selection)
    raw_output = provider.build_profile(request, evidence, selection)
    output = ProjectProfileAgentOutput.model_validate(raw_output)
    output.model_metadata = {
        **output.model_metadata,
        "provider": provider.provider,
        "model": provider.model,
    }
    from guidesync_agent.services.project_profile_validation import (
        has_blocking_findings,
        validate_project_profile_output,
    )

    findings = validate_project_profile_output(output, evidence)
    if has_blocking_findings(findings):
        raise ProjectProfileAgentError("project profile agent output failed validation", findings)
    return ProjectProfileAgentResult(
        output=output,
        selection=selection,
        evidence=evidence,
        validation_findings=findings,
        provider=provider.provider,
        model=provider.model,
        model_metadata={
            "provider": provider.provider,
            "model": provider.model,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            **getattr(provider, "last_metadata", {}),
            **output.model_metadata,
        },
    )


def default_project_profile_agent_provider() -> ProjectProfileAgentProvider:
    provider = os.environ.get("GUIDESYNC_PROJECT_PROFILE_AGENT_PROVIDER", "local_http")
    if provider in {"fake", "fixture"}:
        return FakeProjectProfileAgentProvider()
    return LocalHTTPProjectProfileAgentProvider()


def build_agent_request(
    project: ProjectConfig,
    base_profile: ProjectProfileSnapshot,
    repository_data: list[ProjectProfileRepositoryData],
    reason: str,
) -> ProjectProfileAgentRequest:
    summaries = []
    for repository in repository_data:
        item = repository.repository_map
        source = repository.source_ref
        summaries.append(
            ProjectProfileRepositorySummary(
                project_id=project.id,
                repository_id=item.repository_id,
                name=item.name,
                url=item.url,
                default_branch=item.default_branch,
                current_commit=item.current_commit,
                cache_status=item.cache_status,
                local_path=source.local_path,
                analysis_paths=item.analysis_paths,
                knowledge_base_path=item.knowledge_base_path,
                warnings=repository.warnings,
            )
        )
    return ProjectProfileAgentRequest(
        project_id=project.id,
        profile_id=base_profile.id,
        reason=profile_reason(reason),
        name=project.name,
        description=project.description,
        audience=project.audience,
        documentation_instructions=project.documentation_instructions,
        knowledge_base_repository_id=project.knowledge_base_repository_id,
        knowledge_base_ref=project.knowledge_base_ref,
        knowledge_base_path=project.knowledge_base_path,
        analysis_paths=project.analysis_paths,
        repositories=summaries,
        budget=ProjectProfileToolBudget(),
    )


def collect_file_listings(
    request: ProjectProfileAgentRequest,
) -> list[ProjectProfileFileListing]:
    listings: list[ProjectProfileFileListing] = []
    for repository in request.repositories:
        offset = 0
        while True:
            if repository.local_path:
                listing = list_repository_profile_files_from_root(
                    request.project_id,
                    repository.repository_id,
                    Path(repository.local_path),
                    offset=offset,
                    limit=request.budget.file_listing_page_size,
                )
            else:
                listing = list_repository_profile_files(
                    request.project_id,
                    repository.repository_id,
                    offset=offset,
                    limit=request.budget.file_listing_page_size,
                )
            listings.append(listing)
            if not listing.pagination.next_offset:
                break
            offset = listing.pagination.next_offset
    return listings


def collect_agent_evidence(
    request: ProjectProfileAgentRequest,
    file_listings: list[ProjectProfileFileListing],
    selection: ProjectProfileFileSelection,
) -> ProjectProfileAgentEvidence:
    available = {
        (file.repository_id, file.path)
        for listing in file_listings
        for file in listing.files
    }
    windows = []
    searches: list[RepositorySearchResult] = []
    trace: list[ProjectProfileToolTraceRef] = [
        ProjectProfileToolTraceRef(
            tool_name="list_repository_profile_files",
            repository_id=listing.repository_id,
            output_summary=f"{len(listing.files)} files in page; total {listing.pagination.total}",
            evidence_refs=[file.evidence_ref for file in listing.files[:20]],
            error=listing.error,
        )
        for listing in file_listings
    ]
    total_chars = 0
    for selected in selection.files_to_read[: request.budget.max_tool_calls]:
        if (selected.repository_id, selected.path) not in available:
            continue
        remaining = request.budget.max_total_evidence_chars - total_chars
        if remaining <= 0:
            break
        limit = min(request.budget.max_file_window_chars, remaining)
        local_path = repository_local_path(request, selected.repository_id)
        window = read_repository_profile_file(
            request.project_id,
            selected.repository_id,
            selected.path,
            local_path=local_path,
            limit=limit,
        )
        total_chars += len(window.content)
        windows.append(window)
        trace.append(
            ProjectProfileToolTraceRef(
                tool_name="read_file_window",
                repository_id=selected.repository_id,
                input_summary=selected.path,
                output_summary=f"{len(window.content)} chars read",
                evidence_refs=[evidence_ref(selected.repository_id, selected.path)],
                error=window.error,
            )
        )
    for query in selection.search_queries[: request.budget.max_tool_calls]:
        searches.append(run_search_query(request, query))
        result = searches[-1]
        trace.append(
            ProjectProfileToolTraceRef(
                tool_name="search_repository",
                repository_id=query.repository_id,
                input_summary=query.query,
                output_summary=f"{len(result.matches)} matches; total {result.total}",
                evidence_refs=[
                    f"repo:{match.repository_id}:{match.path}:line:{match.line_number}"
                    for match in result.matches[:20]
                ],
                error=result.error,
            )
        )
    return ProjectProfileAgentEvidence(
        repository_summaries=request.repositories,
        file_listings=file_listings,
        file_windows=windows,
        search_results=searches,
        tool_trace=trace,
    )


def run_search_query(
    request: ProjectProfileAgentRequest,
    query: ProjectProfileSearchQuery,
) -> RepositorySearchResult:
    return search_repository_profile_files(
        request.project_id,
        query.repository_id,
        query.query,
        local_path=repository_local_path(request, query.repository_id),
        path_filters=query.path_filters or None,
        limit=20,
    )


def repository_local_path(
    request: ProjectProfileAgentRequest,
    repository_id: str,
) -> str | None:
    repository = next(
        (item for item in request.repositories if item.repository_id == repository_id),
        None,
    )
    return repository.local_path if repository else None


def profile_reason(reason: str) -> ProjectProfileBuildReason:
    normalized = reason.strip().lower().replace("-", "_")
    aliases = {"project_changed": "project_updated", "manual": "manual_rebuild"}
    try:
        return ProjectProfileBuildReason(aliases.get(normalized, normalized))
    except ValueError:
        return ProjectProfileBuildReason.MANUAL_REBUILD
