from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from guidesync_agent.agent_runtime.model_usage import (
    ModelCallRecordRequest,
    metadata_int,
    metadata_string,
    provider_kind_or_none,
    record_model_call,
)
from guidesync_agent.agent_runtime.project_profile import (
    ProjectProfileAgentError,
    ProjectProfileAgentRunRequest,
    ProjectProfileRepositoryData,
    project_profile_agent_config_metadata,
    run_project_profile_agent,
)
from guidesync_agent.agent_runtime.pydantic_ai import PydanticAgentRunCancelledError
from guidesync_agent.agent_runtime.transcript_types import LLMTranscriptContext
from guidesync_agent.agent_runtime.transcripts import record_llm_transcript_from_metadata
from guidesync_agent.schemas import (
    ModelRole,
    ProjectConfig,
    ProjectProfileAgentEvidence,
    ProjectProfileAgentOutput,
    ProjectProfileEvidenceRef,
    ProjectProfileRepositoryMapItem,
    ProjectProfileSnapshot,
    ProjectProfileSourceRef,
    ProjectProfileStatus,
    ProjectProfileTask,
    ProjectRepository,
    ProjectTaxonomy,
    RepositoryCacheStatus,
)
from guidesync_agent.services.model_roles import provider_config_for_role
from guidesync_agent.services.project_profile.artifacts import write_project_profile_artifacts
from guidesync_agent.services.project_profile.sources import normalized_profile_path
from guidesync_agent.services.repositories.cache import RepositoryCacheService
from guidesync_agent.services.repositories.tasks import RepositoryTaskQueue
from guidesync_agent.services.workflows.cancellation import (
    WorkflowTaskCancelledError,
    raise_if_workflow_task_cancelled,
)
from guidesync_agent.storage import create_project_profile_store, create_project_store

PROJECT_PROFILE_PROMPT_VERSION = "project-profile-analyzer-v2"


@dataclass(frozen=True)
class EmptyProjectProfileInput:
    status: ProjectProfileStatus
    reason: str
    profile_id: str | None = None
    version: int | None = None
    created_at: datetime | None = None


def queue_project_profile_build(
    project: ProjectConfig,
    *,
    reason: str,
) -> ProjectProfileSnapshot:
    queue = RepositoryTaskQueue()
    if not queue.enabled:
        return build_project_profile_for_project(project, reason=reason)

    store = create_project_profile_store()
    profile = empty_project_profile(
        project,
        EmptyProjectProfileInput(
            status=ProjectProfileStatus.QUEUED,
            reason=reason,
        ),
    )
    store.save(profile)
    try:
        queue.send_project_profile(
            ProjectProfileTask(project_id=project.id, profile_id=profile.id, reason=reason)
        )
    except Exception as exc:  # noqa: BLE001 - persist queue failure for API/UI visibility
        error_message = f"failed to enqueue project profile task: {exc}"
        profile = profile.model_copy(
            update={
                "status": ProjectProfileStatus.FAILED,
                "summary": failed_project_profile_summary(error_message),
                "completed_at": datetime.now(UTC),
                "error_message": error_message,
                "warnings": [error_message],
            }
        )
        store.save(profile)
    return profile


def process_project_profile_task(task: ProjectProfileTask) -> ProjectProfileSnapshot | None:
    return build_project_profile(task.project_id, profile_id=task.profile_id, reason=task.reason)


def build_project_profile(
    project_id: str,
    *,
    profile_id: str | None = None,
    reason: str = "manual",
    workflow_task_id: str | None = None,
) -> ProjectProfileSnapshot | None:
    project = create_project_store().get(project_id)
    if project is None:
        return None
    return build_project_profile_for_project(
        project,
        profile_id=profile_id,
        reason=reason,
        workflow_task_id=workflow_task_id,
    )


def build_project_profile_for_project(
    project: ProjectConfig,
    *,
    profile_id: str | None = None,
    reason: str = "manual",
    workflow_task_id: str | None = None,
) -> ProjectProfileSnapshot:
    store = create_project_profile_store()
    existing = store.get(profile_id) if profile_id else None
    created_at = existing.created_at if existing else datetime.now(UTC)
    version = existing.version if existing else next_project_profile_version(project.id)
    running = empty_project_profile(
        project,
        EmptyProjectProfileInput(
            status=ProjectProfileStatus.RUNNING,
            profile_id=profile_id or (existing.id if existing else None),
            version=version,
            created_at=created_at,
            reason=reason,
        ),
    )
    store.save(running)
    try:
        raise_if_workflow_task_cancelled(workflow_task_id)
        profile = analyze_project_profile(
            project,
            running,
            reason=reason,
            workflow_task_id=workflow_task_id,
        )
        profile = record_project_profile_model_usage(profile, workflow_task_id=workflow_task_id)
        profile = write_project_profile_artifacts(project, profile)
        return store.save(profile)
    except (PydanticAgentRunCancelledError, WorkflowTaskCancelledError) as exc:
        message = str(exc) or "Project profile build was cancelled."
        cancelled = running.model_copy(
            update={
                "status": ProjectProfileStatus.CANCELLED,
                "summary": "Project profile build cancelled.",
                "completed_at": datetime.now(UTC),
                "error_message": message,
                "warnings": [*running.warnings, message],
            }
        )
        return store.save(cancelled)
    except Exception as exc:  # noqa: BLE001 - keep failed profile visible for diagnostics
        error_message = str(exc) or exc.__class__.__name__
        validation_findings = (
            exc.validation_findings if isinstance(exc, ProjectProfileAgentError) else []
        )
        failed = running.model_copy(
            update={
                "status": ProjectProfileStatus.FAILED,
                "summary": failed_project_profile_summary(error_message),
                "completed_at": datetime.now(UTC),
                "error_message": error_message,
                "warnings": [*running.warnings, error_message],
                "validation_findings": validation_findings,
            }
        )
        return store.save(failed)


def latest_project_profile(project_id: str) -> ProjectProfileSnapshot | None:
    return create_project_profile_store().latest(project_id)


def list_project_profiles(project_id: str) -> list[ProjectProfileSnapshot]:
    return create_project_profile_store().list_profiles(project_id)


def project_profile_rebuild_needed(
    previous: ProjectConfig,
    current: ProjectConfig,
) -> bool:
    return project_profile_fingerprint(previous) != project_profile_fingerprint(current)


def project_profile_fingerprint(project: ProjectConfig) -> dict[str, object]:
    return {
        "name": project.name,
        "description": project.description,
        "audience": project.audience.value,
        "documentation_instructions": project.documentation_instructions,
        "knowledge_base_repository_id": project.knowledge_base_repository_id,
        "knowledge_base_ref": project.knowledge_base_ref,
        "knowledge_base_path": project.knowledge_base_path,
        "analysis_paths": project.analysis_paths,
        "repositories": [
            {
                "id": repository.id,
                "name": repository.name,
                "url": repository.url,
                "default_branch": repository.default_branch,
                "analysis_paths": repository.analysis_paths,
                "credential_ref": repository.credential_ref,
            }
            for repository in project.repositories
        ],
    }


def empty_project_profile(
    project: ProjectConfig,
    data: EmptyProjectProfileInput,
) -> ProjectProfileSnapshot:
    return ProjectProfileSnapshot(
        id=data.profile_id or f"profile-{uuid4().hex[:10]}",
        project_id=project.id,
        status=data.status,
        version=data.version or next_project_profile_version(project.id),
        prompt_version=PROJECT_PROFILE_PROMPT_VERSION,
        summary=f"Project profile build {data.status.value}: {data.reason}.",
        model_metadata=project_profile_agent_config_metadata(),
        warnings=[],
        uncertainty_notes=[],
        created_at=data.created_at or datetime.now(UTC),
    )


def failed_project_profile_summary(error_message: str) -> str:
    reason = error_message.strip() or "unknown error"
    return f"Project profile build failed: {reason}"


def next_project_profile_version(project_id: str) -> int:
    latest = create_project_profile_store().latest(project_id)
    return 1 if latest is None else latest.version + 1


def analyze_project_profile(
    project: ProjectConfig,
    base_profile: ProjectProfileSnapshot,
    *,
    reason: str = "manual",
    workflow_task_id: str | None = None,
) -> ProjectProfileSnapshot:
    repository_data = []
    for repository in project.repositories:
        raise_if_workflow_task_cancelled(workflow_task_id)
        repository_data.append(inspect_repository(project, repository))
    repository_map = [item[0] for item in repository_data]
    source_refs = [item[1] for item in repository_data]
    warnings = [warning for item in repository_data for warning in item[2]]
    agent_result = run_project_profile_agent(
        ProjectProfileAgentRunRequest(
            project=project,
            base_profile=base_profile,
            repository_data=[
                ProjectProfileRepositoryData(
                    repository_map=item[0],
                    source_ref=item[1],
                    warnings=item[2],
                )
                for item in repository_data
            ],
            reason=reason,
            workflow_task_id=workflow_task_id,
        )
    )
    output = agent_result.output
    taxonomy = project_profile_taxonomy_from_output(output, base_profile)
    profile_evidence = profile_evidence_from_agent_evidence(agent_result.evidence)
    tool_trace_refs = [
        f"project-profile-tool:{index}:{trace.tool_name}:{trace.repository_id or 'project'}"
        for index, trace in enumerate(agent_result.evidence.tool_trace, start=1)
    ]
    return base_profile.model_copy(
        update={
            "status": ProjectProfileStatus.COMPLETED,
            "summary": output.summary,
            "project_description": output.project_description,
            "project_structure": profile_markdown_section(output.project_structure),
            "architecture": profile_markdown_section(output.architecture),
            "core_concepts": output.core_concepts,
            "workflows": [],
            "key_terms": [],
            "agent_context": project_profile_context_from_output(output),
            "taxonomy": taxonomy,
            "profile_evidence": profile_evidence,
            "repository_map": repository_map,
            "source_refs": source_refs,
            "warnings": [*warnings, *agent_result.selection.warnings],
            "uncertainty_notes": [] if profile_evidence else ["No repository evidence was read."],
            "model_metadata": {
                **agent_result.model_metadata,
                "selection": agent_result.selection.model_dump(mode="json"),
                "tool_trace": [
                    trace.model_dump(mode="json") for trace in agent_result.evidence.tool_trace
                ],
            },
            "tool_trace_refs": tool_trace_refs,
            "validation_findings": agent_result.validation_findings,
            "completed_at": datetime.now(UTC),
            "error_message": None,
        }
    )


def project_profile_taxonomy_from_output(
    output: ProjectProfileAgentOutput,
    base_profile: ProjectProfileSnapshot,
) -> ProjectTaxonomy:
    return ProjectTaxonomy(
        version=f"{base_profile.id}:v{base_profile.version}",
        confidence=0.7 if output.categories else 0.3,
        categories=output.categories,
    )


def profile_markdown_section(value: str) -> list[str]:
    stripped = value.strip()
    return [stripped] if stripped else []


def project_profile_context_from_output(output: ProjectProfileAgentOutput) -> str:
    sections = [
        "# Project brief",
        output.project_description.strip(),
    ]
    if output.project_structure.strip():
        sections.extend(["## Project structure", output.project_structure.strip()])
    if output.architecture.strip():
        sections.extend(["## Architecture", output.architecture.strip()])
    if output.core_concepts:
        sections.extend(["## Core concepts", markdown_bullets(output.core_concepts)])
    if output.categories:
        sections.extend(["## Documentation categories", markdown_bullets(output.categories)])
    return "\n\n".join(section for section in sections if section)


def markdown_bullets(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values if value.strip())


def profile_evidence_from_agent_evidence(
    evidence: ProjectProfileAgentEvidence,
) -> list[ProjectProfileEvidenceRef]:
    refs: list[ProjectProfileEvidenceRef] = []
    seen: set[tuple[str | None, str]] = set()

    for window in evidence.file_windows:
        if window.error is None:
            append_profile_evidence_ref(
                refs,
                seen,
                ProjectProfileEvidenceRef(
                    repository_id=window.repository_id,
                    path=window.path,
                    reason="read by project profile agent",
                ),
            )
    for result in evidence.search_results:
        if result.error is not None:
            continue
        for match in result.matches:
            append_profile_evidence_ref(
                refs,
                seen,
                ProjectProfileEvidenceRef(
                    repository_id=match.repository_id,
                    path=match.path,
                    reason=f"matched search query: {result.query}",
                    line=match.line_number,
                ),
            )
    for candidate in listed_profile_evidence_refs(evidence):
        append_profile_evidence_ref(refs, seen, candidate)
    return refs[:40]


def listed_profile_evidence_refs(
    evidence: ProjectProfileAgentEvidence,
) -> list[ProjectProfileEvidenceRef]:
    return [
        ProjectProfileEvidenceRef(
            repository_id=file_ref.repository_id,
            path=file_ref.path,
            reason="listed during project profile",
        )
        for listing in evidence.file_listings
        if listing.error is None
        for file_ref in listing.files
    ]


def append_profile_evidence_ref(
    refs: list[ProjectProfileEvidenceRef],
    seen: set[tuple[str | None, str]],
    candidate: ProjectProfileEvidenceRef,
) -> None:
    normalized_path = (
        candidate.path.removeprefix(f"/repositories/{candidate.repository_id}/")
        if candidate.repository_id
        else candidate.path
    )
    key = (candidate.repository_id, normalized_path)
    if not profile_evidence_path_allowed(normalized_path) or key in seen:
        return
    seen.add(key)
    refs.append(candidate.model_copy(update={"path": normalized_path}))


def profile_evidence_path_allowed(path: str) -> bool:
    return all(not part.startswith(".") for part in path.split("/") if part)


def record_project_profile_model_usage(
    profile: ProjectProfileSnapshot,
    *,
    workflow_task_id: str | None = None,
) -> ProjectProfileSnapshot:
    provider = provider_kind_or_none(metadata_string(profile.model_metadata, "provider"))
    if provider is None:
        return profile
    model = metadata_string(profile.model_metadata, "model") or provider_config_for_role(
        ModelRole.PROJECT_PROFILE_FILE_READER
    ).model
    completed_at = profile.completed_at or datetime.now(UTC)
    latency_ms = metadata_int(profile.model_metadata, "latency_ms")
    started_at = completed_at - timedelta(milliseconds=latency_ms)
    try:
        call_id = f"{profile.id}-{ModelRole.PROJECT_PROFILE_FILE_READER.value}"
        record_model_call(
            ModelCallRecordRequest(
                project_id=profile.project_id,
                run_id=None,
                workflow_task_id=workflow_task_id,
                role=ModelRole.PROJECT_PROFILE_FILE_READER,
                provider=provider,
                model=model,
                base_url=metadata_string(profile.model_metadata, "base_url"),
                started_at=started_at,
                completed_at=completed_at,
                latency_ms=latency_ms,
                metadata=profile.model_metadata,
                error=profile.error_message,
                call_id=call_id,
                prompt_version=profile.prompt_version,
                structured_output_schema="ProjectProfileAgentOutput",
            )
        )
        if not metadata_string(profile.model_metadata, "llm_transcript_id"):
            record_llm_transcript_from_metadata(
                LLMTranscriptContext(
                    project_id=profile.project_id,
                    run_id=None,
                    workflow_task_id=workflow_task_id,
                    model_role=ModelRole.PROJECT_PROFILE_FILE_READER,
                    provider=provider,
                    model=model,
                    metadata=profile.model_metadata,
                    started_at=started_at,
                    model_call_id=call_id,
                    token_ledger_entry_id=call_id,
                    endpoint_type=metadata_string(
                        profile.model_metadata,
                        "endpoint_type",
                    ),
                ),
                completed_at=completed_at,
            )
    except Exception as exc:  # noqa: BLE001 - profile should expose ledger failures
        return profile.model_copy(
            update={
                "warnings": [
                    *profile.warnings,
                    f"model usage or transcript write failed: {exc}",
                ]
            }
        )
    return profile


def inspect_repository(
    project: ProjectConfig,
    repository: ProjectRepository,
) -> tuple[ProjectProfileRepositoryMapItem, ProjectProfileSourceRef, list[str]]:
    cache_service = RepositoryCacheService()
    status_repository = cache_service.status(project.id, repository)
    local_path = status_repository.local_path
    current_commit = status_repository.current_commit
    cache_status = status_repository.cache_status
    direct_path = direct_local_repository_path(repository)
    if cache_status != RepositoryCacheStatus.READY and direct_path is not None:
        local_path = str(direct_path)
        current_commit = cache_service.current_commit(direct_path)
        cache_status = RepositoryCacheStatus.READY
    knowledge_base_path = (
        normalized_profile_path(project.knowledge_base_path)
        if repository.id == selected_knowledge_repository_id(project)
        else None
    )
    warnings = list(status_repository.cache_warnings)
    if cache_status != RepositoryCacheStatus.READY:
        warnings.append(f"repository cache is not ready for {repository.name}")
    source_ref = ProjectProfileSourceRef(
        repository_id=repository.id,
        repository_name=repository.name,
        ref=project.knowledge_base_ref or repository.default_branch,
        commit_sha=current_commit,
        local_path=local_path,
        docs_path=knowledge_base_path,
        analysis_paths=repository.analysis_paths or project.analysis_paths,
    )
    repository_map = ProjectProfileRepositoryMapItem(
        repository_id=repository.id,
        name=repository.name,
        url=repository.url,
        default_branch=repository.default_branch,
        current_commit=current_commit,
        cache_status=cache_status,
        analysis_paths=repository.analysis_paths or project.analysis_paths,
        knowledge_base_path=knowledge_base_path,
    )
    return repository_map, source_ref, warnings


def direct_local_repository_path(repository: ProjectRepository) -> Path | None:
    if "://" in repository.url or not repository.url:
        return None
    candidate = Path(repository.url).expanduser()
    if not candidate.exists():
        return None
    return candidate.resolve()


def selected_knowledge_repository_id(project: ProjectConfig) -> str | None:
    if project.knowledge_base_repository_id:
        return project.knowledge_base_repository_id
    return project.repositories[0].id if project.repositories else None
