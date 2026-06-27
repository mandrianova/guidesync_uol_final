from __future__ import annotations

from pathlib import Path
from typing import cast

from guidesync_agent.schemas import (
    AgentLoopObservation,
    AgentLoopRequest,
    AgentLoopToolCall,
    AgentLoopToolDescriptor,
    AgentLoopToolName,
    JsonValue,
    ProjectProfileAgentEvidence,
    ProjectProfileAgentRequest,
    ProjectProfileFileListing,
    ProjectProfileFileSelection,
    ProjectProfileSearchQuery,
    ProjectProfileSelectedFile,
    ProjectProfileToolTraceRef,
    RepositoryFileWindow,
    RepositorySearchResult,
    ToolError,
)
from guidesync_agent.services.agent_loop_args import (
    int_arg,
    list_arg,
    list_arg_from_mapping,
    string_arg,
    string_arg_from_mapping,
    string_payload,
)
from guidesync_agent.tools.project_profile import (
    evidence_ref,
    list_repository_profile_files,
    list_repository_profile_files_from_root,
    read_repository_profile_file,
    search_repository_profile_files,
)


def project_profile_loop_request(request: ProjectProfileAgentRequest) -> AgentLoopRequest:
    return AgentLoopRequest(
        task_name="project_profile",
        task_goal=(
            "Explore repository evidence freely and return the final "
            "ProjectProfileAgentOutput only when enough evidence has been inspected."
        ),
        project_id=request.project_id,
        profile_id=request.profile_id,
        instructions=(
            "Use tools to list, read, and search repository files. Derive categories, "
            "components, workflows, documentation areas, domain terms, aliases, and "
            "agent context from repository evidence. Do not use a fixed file-selection "
            "pipeline or template taxonomy."
        ),
        context=cast(dict[str, JsonValue], request.model_dump(mode="json", exclude={"budget"})),
        tool_descriptors=project_profile_tool_descriptors(),
    )


def project_profile_tool_descriptors() -> list[AgentLoopToolDescriptor]:
    return [
        AgentLoopToolDescriptor(
            name=AgentLoopToolName.INSPECT_REPOSITORY_SUMMARY,
            description="Return saved project repository metadata and cache state.",
        ),
        AgentLoopToolDescriptor(
            name=AgentLoopToolName.LIST_REPOSITORY_FILES,
            description="List repository files with pagination and optional path filters.",
        ),
        AgentLoopToolDescriptor(
            name=AgentLoopToolName.READ_REPOSITORY_FILE,
            description="Read a bounded window from any non-secret repository file by path.",
        ),
        AgentLoopToolDescriptor(
            name=AgentLoopToolName.SEARCH_REPOSITORY_FILES,
            description="Search readable repository files for a project-specific term.",
        ),
    ]


def execute_project_profile_tool(
    request: ProjectProfileAgentRequest,
    call: AgentLoopToolCall,
) -> AgentLoopObservation:
    repository_id = string_arg(call, "repository_id") or default_repository_id(request)
    if call.tool_name == AgentLoopToolName.INSPECT_REPOSITORY_SUMMARY:
        payload = {"repositories": [item.model_dump(mode="json") for item in request.repositories]}
        return AgentLoopObservation(
            tool_name=call.tool_name,
            arguments=call.arguments,
            output_summary=f"{len(request.repositories)} repositories available",
            payload=cast(dict[str, JsonValue], payload),
        )
    if call.tool_name == AgentLoopToolName.LIST_REPOSITORY_FILES:
        listing = list_repository_profile_files_for_call(request, repository_id, call)
        return AgentLoopObservation(
            tool_name=call.tool_name,
            arguments=call.arguments,
            ok=listing.ok,
            output_summary=(
                f"{len(listing.files)} files returned; total {listing.pagination.total}; "
                f"next_offset={listing.pagination.next_offset}"
            ),
            payload=cast(dict[str, JsonValue], listing.model_dump(mode="json")),
            evidence_refs=[file.evidence_ref for file in listing.files[:20]],
            error_code=listing.error.code if listing.error else None,
            error_message=listing.error.message if listing.error else None,
        )
    if call.tool_name == AgentLoopToolName.READ_REPOSITORY_FILE:
        return read_project_profile_file_observation(request, repository_id, call)
    if call.tool_name == AgentLoopToolName.SEARCH_REPOSITORY_FILES:
        return search_project_profile_observation(request, repository_id, call)
    return unsupported_project_profile_tool(call)


def read_project_profile_file_observation(
    request: ProjectProfileAgentRequest,
    repository_id: str,
    call: AgentLoopToolCall,
) -> AgentLoopObservation:
    path = string_arg(call, "path")
    window = read_repository_profile_file(
        request.project_id,
        repository_id,
        path,
        local_path=repository_local_path(request, repository_id),
        offset=int_arg(call, "offset", 0),
        limit=int_arg(call, "limit", 16_000),
    )
    ref = evidence_ref(repository_id, path) if path else None
    return AgentLoopObservation(
        tool_name=call.tool_name,
        arguments=call.arguments,
        ok=window.ok,
        output_summary=(
            f"{len(window.content)} chars from {window.path}; "
            f"next_offset={window.pagination.next_offset}"
        ),
        payload=cast(dict[str, JsonValue], window.model_dump(mode="json")),
        evidence_refs=[ref] if ref else [],
        artifact_ref=window.artifact_ref,
        error_code=window.error.code if window.error else None,
        error_message=window.error.message if window.error else None,
    )


def search_project_profile_observation(
    request: ProjectProfileAgentRequest,
    repository_id: str,
    call: AgentLoopToolCall,
) -> AgentLoopObservation:
    query = string_arg(call, "query")
    result = search_repository_profile_files(
        request.project_id,
        repository_id,
        query,
        local_path=repository_local_path(request, repository_id),
        path_filters=list_arg(call, "path_filters") or None,
        limit=int_arg(call, "limit", 20),
    )
    refs = [
        f"repo:{match.repository_id}:{match.path}:line:{match.line_number}"
        for match in result.matches[:20]
    ]
    return AgentLoopObservation(
        tool_name=call.tool_name,
        arguments=call.arguments,
        ok=result.ok,
        output_summary=f"{len(result.matches)} matches for {query}; total {result.total}",
        payload=cast(dict[str, JsonValue], result.model_dump(mode="json")),
        evidence_refs=refs,
        error_code=result.error.code if result.error else None,
        error_message=result.error.message if result.error else None,
    )


def list_repository_profile_files_for_call(
    request: ProjectProfileAgentRequest,
    repository_id: str,
    call: AgentLoopToolCall,
) -> ProjectProfileFileListing:
    local_path = repository_local_path(request, repository_id)
    if local_path:
        return list_repository_profile_files_from_root(
            request.project_id,
            repository_id,
            Path(local_path),
            path_filters=list_arg(call, "path_filters") or None,
            offset=int_arg(call, "offset", 0),
            limit=int_arg(call, "limit", 400),
        )
    return list_repository_profile_files(
        request.project_id,
        repository_id,
        path_filters=list_arg(call, "path_filters") or None,
        offset=int_arg(call, "offset", 0),
        limit=int_arg(call, "limit", 400),
    )


def project_profile_evidence_from_observations(
    request: ProjectProfileAgentRequest,
    observations: list[AgentLoopObservation],
) -> ProjectProfileAgentEvidence:
    listings: list[ProjectProfileFileListing] = []
    windows: list[RepositoryFileWindow] = []
    searches: list[RepositorySearchResult] = []
    trace = []
    for observation in observations:
        repository_id = observation_repository_id(observation)
        if observation.tool_name == AgentLoopToolName.LIST_REPOSITORY_FILES:
            listings.append(ProjectProfileFileListing.model_validate(observation.payload))
        elif observation.tool_name == AgentLoopToolName.READ_REPOSITORY_FILE:
            windows.append(RepositoryFileWindow.model_validate(observation.payload))
        elif observation.tool_name == AgentLoopToolName.SEARCH_REPOSITORY_FILES:
            searches.append(RepositorySearchResult.model_validate(observation.payload))
        trace.append(tool_trace_ref(observation, repository_id))
    return ProjectProfileAgentEvidence(
        repository_summaries=request.repositories,
        file_listings=listings,
        file_windows=windows,
        search_results=searches,
        tool_trace=trace,
    )


def project_profile_selection_from_observations(
    observations: list[AgentLoopObservation],
) -> ProjectProfileFileSelection:
    selected = []
    searches = []
    for observation in observations:
        repository_id = observation_repository_id(observation)
        if observation.tool_name == AgentLoopToolName.READ_REPOSITORY_FILE and repository_id:
            selected.append(
                ProjectProfileSelectedFile(
                    repository_id=repository_id,
                    path=string_payload(observation.payload, "path"),
                    reason="read by free agent loop",
                )
            )
        elif observation.tool_name == AgentLoopToolName.SEARCH_REPOSITORY_FILES:
            searches.append(
                ProjectProfileSearchQuery(
                    repository_id=repository_id or "",
                    query=string_payload(observation.payload, "query"),
                    path_filters=list_arg_from_mapping(observation.arguments, "path_filters"),
                    reason="searched by free agent loop",
                )
            )
    return ProjectProfileFileSelection(
        files_to_read=selected,
        search_queries=searches,
        reasoning_summary="Derived from free agent-loop tool observations.",
    )


def tool_trace_ref(
    observation: AgentLoopObservation,
    repository_id: str | None,
) -> ProjectProfileToolTraceRef:
    return ProjectProfileToolTraceRef(
        tool_name=observation.tool_name.value,
        repository_id=repository_id,
        input_summary=str(observation.arguments)[:500],
        output_summary=observation.output_summary,
        evidence_refs=observation.evidence_refs,
        artifact_ref=observation.artifact_ref,
        error=(
            None
            if observation.error_code is None
            else ToolError(
                code=observation.error_code,
                message=observation.error_message or observation.error_code,
            )
        ),
    )


def unsupported_project_profile_tool(call: AgentLoopToolCall) -> AgentLoopObservation:
    return AgentLoopObservation(
        tool_name=call.tool_name,
        arguments=call.arguments,
        ok=False,
        output_summary=f"Unsupported project-profile tool: {call.tool_name.value}",
        error_code="unsupported_tool",
        error_message=f"Unsupported project-profile tool: {call.tool_name.value}",
    )


def observation_repository_id(observation: AgentLoopObservation) -> str | None:
    return (
        string_payload(observation.payload, "repository_id")
        or string_arg_from_mapping(observation.arguments, "repository_id")
        or None
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


def default_repository_id(request: ProjectProfileAgentRequest) -> str:
    return request.repositories[0].repository_id if request.repositories else ""
