from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field

from guidesync_agent.agent_runtime.loop import AgentLoopExecution, run_agent_loop
from guidesync_agent.agent_runtime.pydantic_ai import (
    PydanticAgentRunRequest,
    run_pydantic_agent_sync,
)
from guidesync_agent.prompts.loader import PromptFile, load_prompt_file
from guidesync_agent.schemas import (
    AgentLoopModelAction,
    AgentLoopObservation,
    AgentLoopPromptContext,
    ProjectConfig,
    ProjectProfileAgentOutput,
    ProjectProfileAgentRequest,
    ProjectProfileAgentResult,
    ProjectProfileBuildReason,
    ProjectProfileRepositoryMapItem,
    ProjectProfileRepositorySummary,
    ProjectProfileSnapshot,
    ProjectProfileSourceRef,
    ProjectProfileToolBudget,
    ValidationFinding,
)
from guidesync_agent.schemas.model_roles import ModelRole
from guidesync_agent.services.model_roles import (
    model_role_settings_from_settings,
    provider_config_for_role,
)
from guidesync_agent.services.project_profile_evidence_normalization import (
    canonicalize_project_profile_output,
)
from guidesync_agent.tools.policy import guarded_agent_loop_executor
from guidesync_agent.tools.project_profile_agent import (
    execute_project_profile_tool,
    initial_project_profile_observations,
    project_profile_evidence_from_observations,
    project_profile_loop_request,
    project_profile_selection_from_observations,
    project_profile_tool_definitions,
    register_project_profile_agent_tools,
)

PROJECT_PROFILE_ANALYZER_PROMPT_PATH = "project_profile/analyzer.md"
PROJECT_PROFILE_ANALYZER_PROMPT_VERSION = "project-profile-analyzer-v2"
PROJECT_PROFILE_CONTEXT_PROMPT_PATH = "project_profile/runtime_context.md"
PROJECT_PROFILE_CONTEXT_PROMPT_VERSION = "project-profile-runtime-context-v1"


class ProjectProfileAgentProvider(Protocol):
    provider: str
    model: str

    def next_action(self, context: AgentLoopPromptContext) -> AgentLoopModelAction: ...


class ProjectProfileAgentError(ValueError):
    def __init__(self, message: str, findings: list[ValidationFinding]) -> None:
        super().__init__(message)
        self.validation_findings = findings


@dataclass
class ProjectProfileRepositoryData:
    repository_map: ProjectProfileRepositoryMapItem
    source_ref: ProjectProfileSourceRef
    warnings: list[str]


@dataclass(frozen=True)
class ProjectProfileAgentRunRequest:
    project: ProjectConfig
    base_profile: ProjectProfileSnapshot
    repository_data: list[ProjectProfileRepositoryData]
    reason: str = "manual"
    workflow_task_id: str | None = None


@dataclass
class ProjectProfilePydanticDeps:
    request: ProjectProfileAgentRequest
    observations: list[Any]
    tool_calls: int = 0


class ProjectProfilePromptInput(BaseModel):
    project: ProjectProfileAgentRequest
    initial_observations: list[AgentLoopObservation] = Field(default_factory=list)


def run_project_profile_agent(
    run_request: ProjectProfileAgentRunRequest,
    provider: ProjectProfileAgentProvider | None = None,
) -> ProjectProfileAgentResult:
    if provider is None:
        return run_pydantic_project_profile_agent(
            run_request.project,
            run_request.base_profile,
            run_request.repository_data,
            reason=run_request.reason,
            workflow_task_id=run_request.workflow_task_id,
        )
    started = time.perf_counter()
    request = build_agent_request(
        run_request.project,
        run_request.base_profile,
        run_request.repository_data,
        run_request.reason,
    )
    loop_result = run_agent_loop(
        AgentLoopExecution(
            request=project_profile_loop_request(request),
            provider=provider,
            execute_tool=guarded_agent_loop_executor(
                project_profile_tool_definitions(),
                lambda call: execute_project_profile_tool(request, call),
            ),
            final_output_model=ProjectProfileAgentOutput,
            initial_observations=initial_project_profile_observations(request),
        )
    )
    evidence = project_profile_evidence_from_observations(request, loop_result.observations)
    selection = project_profile_selection_from_observations(loop_result.observations)
    output = canonicalize_project_profile_output(
        ProjectProfileAgentOutput.model_validate(loop_result.final_output),
        evidence,
    )
    output_metadata = {
        "provider": provider.provider,
        "model": provider.model,
        "agent_loop": "free_tool_loop",
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
            **loop_result.model_metadata,
            "compaction_checkpoints": [
                checkpoint.model_dump(mode="json")
                for checkpoint in loop_result.compaction_checkpoints
            ],
            **output_metadata,
        },
    )


def project_profile_agent_config_metadata() -> dict[str, Any]:
    return model_role_settings_from_settings(
        ModelRole.PROJECT_PROFILE_FILE_READER
    ).evidence_metadata()


def run_pydantic_project_profile_agent(
    project: ProjectConfig,
    base_profile: ProjectProfileSnapshot,
    repository_data: list[ProjectProfileRepositoryData],
    *,
    reason: str,
    workflow_task_id: str | None,
) -> ProjectProfileAgentResult:
    started = time.perf_counter()
    config = provider_config_for_role(ModelRole.PROJECT_PROFILE_FILE_READER)
    request = build_agent_request(project, base_profile, repository_data, reason)
    initial_observations = initial_project_profile_observations(request)
    deps = ProjectProfilePydanticDeps(
        request=request,
        observations=initial_observations,
    )
    prompt_file = project_profile_prompt()
    context_prompt = project_profile_context_prompt()
    prompt = pydantic_project_profile_prompt(
        request,
        deps.observations,
        context_prompt=context_prompt,
    )
    runtime_result = run_pydantic_agent_sync(
        PydanticAgentRunRequest(
            prompt=prompt,
            instructions=prompt_file.content,
            output_model=ProjectProfileAgentOutput,
            deps=deps,
            deps_type=ProjectProfilePydanticDeps,
            config=config,
            model_role=ModelRole.PROJECT_PROFILE_FILE_READER,
            project_id=project.id,
            workflow_task_id=workflow_task_id,
            model_call_id=(
                f"{base_profile.id}-{ModelRole.PROJECT_PROFILE_FILE_READER.value}"
            ),
            token_ledger_entry_id=(
                f"{base_profile.id}-{ModelRole.PROJECT_PROFILE_FILE_READER.value}"
            ),
            prompt_metadata={
                **prompt_file.usage_metadata("project_profile_agent"),
                **context_prompt.usage_metadata("project_profile_context"),
            },
            register_tools=register_project_profile_agent_tools,
        )
    )
    evidence = project_profile_evidence_from_observations(request, deps.observations)
    selection = project_profile_selection_from_observations(deps.observations)
    output = canonicalize_project_profile_output(
        ProjectProfileAgentOutput.model_validate(runtime_result.output),
        evidence,
    )
    output_metadata = {
        "provider": config.provider.value,
        "model": config.model,
        "agent_runtime": "pydantic_ai",
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
        provider=config.provider.value,
        model=config.model,
        model_metadata={
            "provider": config.provider.value,
            "model": config.model,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            **config.metadata,
            **runtime_result.usage,
            "prompt_input_chars": len(prompt),
            "tool_call_count": deps.tool_calls,
            "initial_observations": len(initial_observations),
            "agent_runtime": "pydantic_ai",
            "selection": selection.model_dump(mode="json"),
            **output_metadata,
        },
    )


def pydantic_project_profile_prompt(
    request: ProjectProfileAgentRequest,
    observations: list[Any],
    context_prompt: PromptFile | None = None,
) -> str:
    prompt_input = ProjectProfilePromptInput(
        project=request,
        initial_observations=[
            AgentLoopObservation.model_validate(observation) for observation in observations
        ],
    )
    prompt_file = context_prompt or project_profile_context_prompt()
    return f"{prompt_file.content.rstrip()}\n\n{prompt_input.model_dump_json(indent=2)}"


def project_profile_prompt() -> PromptFile:
    return load_prompt_file(
        PROJECT_PROFILE_ANALYZER_PROMPT_PATH,
        version=PROJECT_PROFILE_ANALYZER_PROMPT_VERSION,
    )


def project_profile_context_prompt() -> PromptFile:
    return load_prompt_file(
        PROJECT_PROFILE_CONTEXT_PROMPT_PATH,
        version=PROJECT_PROFILE_CONTEXT_PROMPT_VERSION,
    )


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


def profile_reason(reason: str) -> ProjectProfileBuildReason:
    normalized = reason.strip().lower().replace("-", "_")
    aliases = {"project_changed": "project_updated", "manual": "manual_rebuild"}
    try:
        return ProjectProfileBuildReason(aliases.get(normalized, normalized))
    except ValueError:
        return ProjectProfileBuildReason.MANUAL_REBUILD
