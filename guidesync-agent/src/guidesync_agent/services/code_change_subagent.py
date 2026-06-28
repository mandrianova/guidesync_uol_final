from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError
from pydantic_ai import Agent, RunContext

from guidesync_agent.llm.local_http import (
    local_chat_payload,
    local_http_endpoint_mode,
    local_message_content,
    post_local_chat,
)
from guidesync_agent.llm.structured_output import select_structured_output
from guidesync_agent.prompts.loader import PromptFile, load_prompt_file
from guidesync_agent.schemas import (
    AgentLoopModelAction,
    AgentLoopPromptContext,
    AgentLoopToolCall,
    AgentLoopToolName,
    CodeChangeAnalysis,
    CodeChangeAnalysisArtifact,
    CodeChangeEvidenceRef,
    FileChangeSummary,
    KnowledgeConceptKind,
    ProjectProfileSnapshot,
    ProviderKind,
    ValidationFinding,
)
from guidesync_agent.schemas.model_roles import ModelRole
from guidesync_agent.services.agent_loop import run_agent_loop
from guidesync_agent.services.agent_tool_policy import guarded_agent_loop_executor
from guidesync_agent.services.code_change_agent_evidence import (
    code_change_evidence_refs_from_observations,
    combined_evidence_refs,
)
from guidesync_agent.services.code_change_agent_loop import (
    CodeChangeLoopAction,
    code_change_loop_request,
    code_change_loop_user_prompt,
    code_change_tool_definitions,
    execute_code_change_tool,
    initial_code_change_observations,
)
from guidesync_agent.services.code_change_analysis_output import (
    annotate_change_analysis,
    summary_from_analysis,
)
from guidesync_agent.services.code_change_model_usage import (
    CodeChangeModelUsageContext,
    code_change_call_id,
    provider_kind_or_none,
    record_code_change_model_usage,
)
from guidesync_agent.services.code_change_subagent_constants import (
    CODE_CHANGE_ANALYZER_PROMPT_PATH,
    CODE_CHANGE_ANALYZER_PROMPT_VERSION,
)
from guidesync_agent.services.code_change_subagent_taxonomy import (
    candidate_terms_for_terms,
    dedupe_preserve_order,
    sanitize_taxonomy_matches,
    taxonomy_matches_for_terms,
    values_for_kind,
)
from guidesync_agent.services.llm_transcripts import (
    local_http_transcript_payload,
    record_llm_transcript_from_metadata,
)
from guidesync_agent.services.model_roles import provider_config_for_role
from guidesync_agent.services.model_usage import (
    endpoint_host_hash,
    merge_local_response_usage,
    sanitized_model_metadata,
)
from guidesync_agent.services.pydantic_agent_runtime import run_pydantic_agent_sync


class CodeChangeAnalysisEvidence(BaseModel):
    diff: str = ""
    current_file: str = ""
    diff_truncated: bool = False
    current_file_truncated: bool = False
    evidence_refs: list[CodeChangeEvidenceRef] = Field(default_factory=list)


class CodeChangeAnalysisRequest(BaseModel):
    run_id: str | None = None
    workflow_task_id: str | None = None
    project_id: str
    repository_id: str
    path: str
    status: str
    goal: str
    audience: str
    fallback_summary: FileChangeSummary
    evidence: CodeChangeAnalysisEvidence
    project_profile: ProjectProfileSnapshot | None = None


class CodeChangeAnalysisProvider(Protocol):
    provider: str
    model: str

    def analyze(self, request: CodeChangeAnalysisRequest) -> object: ...


@dataclass
class CodeChangeSubagentResult:
    summary: FileChangeSummary
    artifact: CodeChangeAnalysisArtifact


@dataclass
class CodeChangePydanticDeps:
    request: CodeChangeAnalysisRequest
    observations: list[Any]
    tool_calls: int = 0


class DeterministicCodeChangeAnalysisProvider:
    provider = "deterministic"
    model = "heuristic-fallback"

    def analyze(self, request: CodeChangeAnalysisRequest) -> object:
        taxonomy = request.project_profile.taxonomy if request.project_profile else None
        key_terms = dedupe_preserve_order(
            [
                *request.fallback_summary.documentation_keywords,
                *request.fallback_summary.docs_to_search,
            ]
        )[:12]
        matches = taxonomy_matches_for_terms(key_terms, taxonomy, request.evidence.evidence_refs)
        candidates = candidate_terms_for_terms(key_terms, taxonomy, request.evidence.evidence_refs)
        return CodeChangeAnalysis(
            what_changed=request.fallback_summary.technical_summary,
            technical_summary=request.fallback_summary.technical_summary,
            user_or_product_impact=request.fallback_summary.product_impact,
            affected_components=values_for_kind(matches, KnowledgeConceptKind.COMPONENT),
            affected_workflows=values_for_kind(matches, KnowledgeConceptKind.WORKFLOW),
            documentation_search_intents=request.fallback_summary.docs_to_search,
            taxonomy_matches=matches,
            candidate_taxonomy_updates=candidates,
            key_terms_from_code=key_terms,
            needs_screenshot_check="ui" in request.fallback_summary.docs_to_search,
            uncertainty_notes=request.fallback_summary.risk_notes,
            evidence_refs=[ref.source for ref in request.evidence.evidence_refs],
            needs_main_agent_review=request.fallback_summary.needs_main_agent_review,
        )


class PydanticAICodeChangeAnalysisProvider:
    provider = ProviderKind.PYDANTIC_AI.value

    def __init__(self) -> None:
        self.config = provider_config_for_role(ModelRole.CODE_CHANGE_ANALYSIS)
        self.model = self.config.model
        self.last_metadata: dict[str, Any] = {}
        self.last_evidence_refs: list[CodeChangeEvidenceRef] = []

    def analyze(self, request: CodeChangeAnalysisRequest) -> object:
        started_at = datetime.now(UTC)
        prompt = code_change_analyzer_prompt()
        initial_observations = initial_code_change_observations(request)
        deps = CodeChangePydanticDeps(request=request, observations=initial_observations)
        call_id = code_change_call_id(
            CodeChangeModelUsageContext(
                project_id=request.project_id,
                run_id=request.run_id,
                workflow_task_id=request.workflow_task_id,
                repository_id=request.repository_id,
                path=request.path,
                provider=self.provider,
                model=self.model,
                metadata={},
                started_at=started_at,
                completed_at=started_at,
            )
        )
        user_prompt = pydantic_code_change_prompt(request, prompt, initial_observations)
        runtime_result = run_pydantic_agent_sync(
            prompt=user_prompt,
            instructions=prompt.content,
            output_model=CodeChangeAnalysis,
            deps=deps,
            deps_type=CodeChangePydanticDeps,
            config=self.config,
            model_role=ModelRole.CODE_CHANGE_ANALYSIS,
            project_id=request.project_id,
            run_id=request.run_id,
            workflow_task_id=request.workflow_task_id,
            model_call_id=call_id,
            token_ledger_entry_id=call_id,
            prompt_metadata=prompt.usage_metadata("code_change_analysis"),
            register_tools=register_code_change_agent_tools,
        )
        self.last_evidence_refs = code_change_evidence_refs_from_observations(
            deps.observations,
            request.evidence.evidence_refs,
        )
        self.last_metadata = sanitized_model_metadata(
            {
                **self.config.metadata,
                **prompt.usage_metadata("code_change_analysis"),
                **runtime_result.usage,
                "model_turn_count": 1,
                "tool_call_count": deps.tool_calls,
                "initial_observations": len(initial_observations),
                "prompt_input_chars": len(user_prompt),
                "agent_runtime": "pydantic_ai",
            }
        )
        return runtime_result.output


class LocalHTTPCodeChangeAnalysisProvider:
    provider = "local_http"

    def __init__(self) -> None:
        self.config = provider_config_for_role(ModelRole.CODE_CHANGE_ANALYSIS)
        self.base_url = self.config.base_url or ""
        self.model = self.config.model
        self.timeout_seconds = self.config.timeout_seconds
        self.last_metadata: dict[str, Any] = {}
        self.last_evidence_refs: list[CodeChangeEvidenceRef] = []
        self.last_usage: dict[str, Any] = {}
        self.transcript_exchanges: list[dict[str, Any]] = []

    def analyze(self, request: CodeChangeAnalysisRequest) -> object:
        prompt = code_change_analyzer_prompt()
        self.last_usage = {}
        self.transcript_exchanges = []
        loop_result = run_agent_loop(
            request=code_change_loop_request(request, prompt),
            provider=self,
            execute_tool=guarded_agent_loop_executor(
                code_change_tool_definitions(),
                lambda call: execute_code_change_tool(request, call),
            ),
            final_output_model=CodeChangeAnalysis,
            initial_observations=initial_code_change_observations(request),
        )
        self.last_evidence_refs = code_change_evidence_refs_from_observations(
            loop_result.observations,
            request.evidence.evidence_refs,
        )
        self.last_metadata = sanitized_model_metadata(
            {
                **prompt.usage_metadata("code_change_analysis"),
                **self.structured_call_metadata(CodeChangeLoopAction, "loop_action"),
                **loop_result.model_metadata,
                **self.last_usage,
                "base_url_host_hash": endpoint_host_hash(self.base_url),
                "model_turn_count": loop_result.model_metadata.get("loop_steps", 1),
                "tool_call_count": loop_result.model_metadata.get("tool_observations", 0),
                "compaction_checkpoints": [
                    checkpoint.model_dump(mode="json")
                    for checkpoint in loop_result.compaction_checkpoints
                ],
                "llm_transcript_payload": {
                    "source": "local_http",
                    "exchanges": self.transcript_exchanges,
                    "tool_summary": {
                        "tool_call_count": loop_result.model_metadata.get(
                            "tool_observations",
                            0,
                        ),
                        "tool_calls": [
                            {
                                "name": observation.tool_name.value,
                                "arguments_summary": observation.arguments,
                                "result_status": observation.result_status.value,
                                "evidence_refs": observation.evidence_refs,
                                "artifact_refs": (
                                    [observation.artifact_ref]
                                    if observation.artifact_ref
                                    else []
                                ),
                            }
                            for observation in loop_result.observations
                        ],
                    },
                },
            }
        )
        return loop_result.final_output

    def next_action(self, context: AgentLoopPromptContext) -> AgentLoopModelAction:
        prompt = code_change_analyzer_prompt()
        raw = self.structured_call(
            prompt.content,
            code_change_loop_user_prompt(context),
            CodeChangeLoopAction,
            stage="loop_action",
        )
        return CodeChangeLoopAction.model_validate(raw).to_agent_loop_action()

    def structured_call(
        self,
        system_prompt: str,
        user_prompt: str,
        output_model: type[BaseModel],
        *,
        stage: str,
    ) -> dict[str, Any]:
        config = self.config.model_copy(update={"provider": ProviderKind.LOCAL_HTTP})
        endpoint = local_http_endpoint_mode(self.base_url)
        structured_output = select_structured_output(
            config,
            output_model,
            requires_tools=False,
        )
        payload = local_chat_payload(
            config,
            system_prompt,
            user_prompt,
            output_model=output_model,
            selection=structured_output,
            endpoint=endpoint,
        )
        body = post_local_chat(
            self.base_url,
            payload,
            self.timeout_seconds,
            config.api_key,
            endpoint=endpoint,
        )
        self.last_usage = merge_local_response_usage(self.last_usage, body)
        content = local_message_content(body)
        self.transcript_exchanges.append(
            local_http_transcript_payload(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                request_payload=payload,
                response_payload=body,
                output_text=content,
                prompt_metadata=self.structured_call_metadata(output_model, stage),
            )
        )
        return json.loads(content)

    def structured_call_metadata(
        self,
        output_model: type[BaseModel],
        stage: str,
    ) -> dict[str, Any]:
        config = self.config.model_copy(update={"provider": ProviderKind.LOCAL_HTTP})
        selection = select_structured_output(config, output_model, requires_tools=False)
        return {
            **self.config.metadata,
            **selection.usage_metadata(f"code_change_analysis_{stage}"),
        }


class CodeChangePrompt(BaseModel):
    system: str
    user: str
    metadata: dict[str, str] = Field(default_factory=dict)


def analyze_code_change_with_subagent(
    request: CodeChangeAnalysisRequest,
    provider: CodeChangeAnalysisProvider | None = None,
) -> CodeChangeSubagentResult:
    provider = provider or default_code_change_analysis_provider()
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    findings: list[ValidationFinding] = []
    try:
        raw_analysis = provider.analyze(request)
        analysis = CodeChangeAnalysis.model_validate(raw_analysis)
        evidence_refs = combined_evidence_refs(
            request.evidence.evidence_refs,
            getattr(provider, "last_evidence_refs", []),
        )
        analysis, taxonomy_findings = sanitize_taxonomy_matches(
            analysis,
            request.project_profile.taxonomy if request.project_profile else None,
        )
        findings.extend(taxonomy_findings)
        findings.extend(validate_code_change_analysis(analysis, evidence_refs))
        if has_blocking_findings(findings):
            raise ValueError("model output failed code-change validation")
    except (
        KeyError,
        TypeError,
        ValidationError,
        ValueError,
        RuntimeError,
        TimeoutError,
        OSError,
    ) as exc:
        fallback_provider = DeterministicCodeChangeAnalysisProvider()
        analysis = CodeChangeAnalysis.model_validate(fallback_provider.analyze(request))
        evidence_refs = request.evidence.evidence_refs
        findings.append(
            ValidationFinding(
                severity="warning",
                check="code-change-analysis.fallback",
                message=f"Model-backed change analysis fell back to deterministic output: {exc}",
                evidence_refs=[ref.source for ref in request.evidence.evidence_refs],
            )
        )
        provider = fallback_provider

    annotation_run_id, annotation_metadata = annotate_change_analysis(request, analysis)
    completed_at = datetime.now(UTC)
    model_metadata = {
        "latency_ms": int((time.perf_counter() - started) * 1000),
        **getattr(provider, "last_metadata", {}),
    }
    usage_finding = record_code_change_model_usage(
        CodeChangeModelUsageContext(
            project_id=request.project_id,
            run_id=request.run_id,
            workflow_task_id=request.workflow_task_id,
            repository_id=request.repository_id,
            path=request.path,
            provider=provider.provider,
            model=provider.model,
            metadata=model_metadata,
            started_at=started_at,
            completed_at=completed_at,
        )
    )
    if usage_finding is not None:
        findings.append(usage_finding)
    transcript_finding = record_code_change_transcript(
        request,
        provider,
        model_metadata,
        started_at,
        completed_at,
    )
    if transcript_finding is not None:
        findings.append(transcript_finding)
    summary = summary_from_analysis(
        request,
        analysis,
        provider=provider,
        prompt_version=CODE_CHANGE_ANALYZER_PROMPT_VERSION,
        annotation_run_id=annotation_run_id,
        annotation_metadata=annotation_metadata,
        findings=findings,
    )
    artifact = CodeChangeAnalysisArtifact(
        prompt_version=CODE_CHANGE_ANALYZER_PROMPT_VERSION,
        repository_id=request.repository_id,
        path=request.path,
        status=request.status,
        provider=provider.provider,
        model=provider.model,
        model_metadata=model_metadata,
        evidence_refs=evidence_refs,
        analysis=analysis,
        annotation_run_id=annotation_run_id,
        validation_findings=findings,
    )
    return CodeChangeSubagentResult(summary=summary, artifact=artifact)


def record_code_change_transcript(
    request: CodeChangeAnalysisRequest,
    provider: CodeChangeAnalysisProvider,
    metadata: dict[str, Any],
    started_at: datetime,
    completed_at: datetime,
) -> ValidationFinding | None:
    provider_kind = provider_kind_or_none(provider.provider)
    if provider_kind is None:
        return None
    if isinstance(metadata.get("llm_transcript_id"), str):
        return None
    context = CodeChangeModelUsageContext(
        project_id=request.project_id,
        run_id=request.run_id,
        workflow_task_id=request.workflow_task_id,
        repository_id=request.repository_id,
        path=request.path,
        provider=provider.provider,
        model=provider.model,
        metadata=metadata,
        started_at=started_at,
        completed_at=completed_at,
    )
    try:
        call_id = code_change_call_id(context)
        record_llm_transcript_from_metadata(
            project_id=request.project_id,
            run_id=request.run_id,
            workflow_task_id=request.workflow_task_id,
            model_role=ModelRole.CODE_CHANGE_ANALYSIS,
            provider=provider_kind,
            model=provider.model,
            metadata=metadata,
            started_at=started_at,
            completed_at=completed_at,
            model_call_id=call_id,
            token_ledger_entry_id=call_id,
            endpoint_type=(
                metadata.get("endpoint_type")
                if isinstance(metadata.get("endpoint_type"), str)
                else None
            ),
        )
    except Exception as exc:  # noqa: BLE001 - workflow should surface transcript failures
        return ValidationFinding(
            severity="warning",
            check="llm-transcript",
            message=f"Code-change LLM transcript write failed: {exc}",
            evidence_refs=[f"file:{request.repository_id}:{request.path}"],
        )
    return None


def default_code_change_analysis_provider() -> CodeChangeAnalysisProvider:
    configured = os.environ.get("GUIDESYNC_CODE_CHANGE_ANALYSIS_PROVIDER", "pydantic_ai")
    if configured in {"deterministic", "fake", "fixture"}:
        return DeterministicCodeChangeAnalysisProvider()
    if configured == "local_http":
        return LocalHTTPCodeChangeAnalysisProvider()
    return PydanticAICodeChangeAnalysisProvider()


def register_code_change_agent_tools(
    agent: Agent[CodeChangePydanticDeps, CodeChangeAnalysis],
) -> None:
    def execute(ctx: RunContext[CodeChangePydanticDeps], call: AgentLoopToolCall) -> dict[str, Any]:
        executor = guarded_agent_loop_executor(
            code_change_tool_definitions(),
            lambda tool_call: execute_code_change_tool(ctx.deps.request, tool_call),
        )
        observation = executor(call)
        ctx.deps.observations.append(observation)
        ctx.deps.tool_calls += 1
        return observation.model_dump(mode="json")

    @agent.tool
    def read_raw_diff(
        ctx: RunContext[CodeChangePydanticDeps],
        repository_id: str | None = None,
        path: str | None = None,
        base_ref: str | None = None,
        head_ref: str = "HEAD",
        offset: int = 0,
        limit: int = 16000,
    ) -> dict[str, Any]:
        """Read a bounded raw git diff window for the changed file or repository."""
        args: dict[str, Any] = {"head_ref": head_ref, "offset": offset, "limit": limit}
        if repository_id:
            args["repository_id"] = repository_id
        if path:
            args["path"] = path
        if base_ref:
            args["base_ref"] = base_ref
        return execute(
            ctx,
            AgentLoopToolCall(tool_name=AgentLoopToolName.READ_RAW_DIFF, arguments=args),
        )

    @agent.tool
    def read_repository_file(
        ctx: RunContext[CodeChangePydanticDeps],
        path: str,
        repository_id: str | None = None,
        offset: int = 0,
        limit: int = 16000,
    ) -> dict[str, Any]:
        """Read a bounded repository file window by path."""
        args: dict[str, Any] = {"path": path, "offset": offset, "limit": limit}
        if repository_id:
            args["repository_id"] = repository_id
        return execute(
            ctx,
            AgentLoopToolCall(
                tool_name=AgentLoopToolName.READ_REPOSITORY_FILE,
                arguments=args,
            ),
        )

    @agent.tool
    def list_repository_files(
        ctx: RunContext[CodeChangePydanticDeps],
        repository_id: str | None = None,
        path_filters: list[str] | None = None,
        offset: int = 0,
        limit: int = 400,
    ) -> dict[str, Any]:
        """List one repository directory level with pagination."""
        args: dict[str, Any] = {"offset": offset, "limit": limit}
        if repository_id:
            args["repository_id"] = repository_id
        if path_filters:
            args["path_filters"] = path_filters
        return execute(
            ctx,
            AgentLoopToolCall(
                tool_name=AgentLoopToolName.LIST_REPOSITORY_FILES,
                arguments=args,
            ),
        )

    @agent.tool
    def search_repository_files(
        ctx: RunContext[CodeChangePydanticDeps],
        query: str,
        repository_id: str | None = None,
        path_filters: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search repository files for relevant terms or project-specific names."""
        args: dict[str, Any] = {"query": query, "limit": limit}
        if repository_id:
            args["repository_id"] = repository_id
        if path_filters:
            args["path_filters"] = path_filters
        return execute(
            ctx,
            AgentLoopToolCall(
                tool_name=AgentLoopToolName.SEARCH_REPOSITORY_FILES,
                arguments=args,
            ),
        )

    @agent.tool
    def read_project_profile(ctx: RunContext[CodeChangePydanticDeps]) -> dict[str, Any]:
        """Read the latest project profile context and controlled taxonomy."""
        return execute(ctx, AgentLoopToolCall(tool_name=AgentLoopToolName.READ_PROJECT_PROFILE))

    @agent.tool
    def search_knowledge_base(
        ctx: RunContext[CodeChangePydanticDeps],
        query: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search indexed documentation and generated knowledge for a query."""
        return execute(
            ctx,
            AgentLoopToolCall(
                tool_name=AgentLoopToolName.SEARCH_KNOWLEDGE_BASE,
                arguments={"query": query, "limit": limit},
            ),
        )

    @agent.tool
    def read_knowledge_document(
        ctx: RunContext[CodeChangePydanticDeps],
        document_id: str,
        offset: int = 0,
        limit: int = 16000,
    ) -> dict[str, Any]:
        """Read a bounded preview of an indexed knowledge document."""
        return execute(
            ctx,
            AgentLoopToolCall(
                tool_name=AgentLoopToolName.READ_KNOWLEDGE_DOCUMENT,
                arguments={"document_id": document_id, "offset": offset, "limit": limit},
            ),
        )


def pydantic_code_change_prompt(
    request: CodeChangeAnalysisRequest,
    prompt: PromptFile,
    observations: list[Any],
) -> str:
    return code_change_loop_request(request, prompt).model_dump_json(indent=2) + (
        "\n\nInitial observations:\n"
        + "\n".join(
            observation.model_dump_json(indent=2)
            for observation in observations
            if hasattr(observation, "model_dump_json")
        )
    )


def validate_code_change_analysis(
    analysis: CodeChangeAnalysis,
    evidence_refs: list[CodeChangeEvidenceRef],
) -> list[ValidationFinding]:
    allowed_refs = {ref.source for ref in evidence_refs}
    findings: list[ValidationFinding] = []
    if not analysis.technical_summary.strip():
        findings.append(model_output_error("technical_summary is required", allowed_refs))
    if not analysis.documentation_search_intents:
        findings.append(
            model_output_error("documentation_search_intents is required", allowed_refs)
        )
    if not analysis.evidence_refs:
        findings.append(model_output_error("evidence_refs are required", allowed_refs))
    unsupported_refs = [ref for ref in analysis.evidence_refs if ref not in allowed_refs]
    if unsupported_refs:
        findings.append(
            ValidationFinding(
                severity="warning",
                check="code-change-analysis.evidence",
                message=f"Model referenced unknown evidence refs: {', '.join(unsupported_refs)}",
                evidence_refs=unsupported_refs,
            )
        )
    return findings


def model_output_error(message: str, evidence_refs: set[str]) -> ValidationFinding:
    return ValidationFinding(
        severity="error",
        check="code-change-analysis.output",
        message=message,
        evidence_refs=sorted(evidence_refs),
    )


def has_blocking_findings(findings: list[ValidationFinding]) -> bool:
    return any(finding.severity == "error" for finding in findings)


def code_change_prompt(request: CodeChangeAnalysisRequest) -> CodeChangePrompt:
    prompt = code_change_analyzer_prompt()
    user = json.dumps(
        {
            "goal": request.goal,
            "audience": request.audience,
            "repository_id": request.repository_id,
            "path": request.path,
            "status": request.status,
            "project_profile": request.project_profile.model_dump(mode="json")
            if request.project_profile
            else None,
            "evidence_refs": [
                ref.model_dump(mode="json") for ref in request.evidence.evidence_refs
            ],
            "diff_window": request.evidence.diff,
            "current_file_window": request.evidence.current_file,
        },
        indent=2,
    )
    return CodeChangePrompt(
        system=prompt.content,
        user=user,
        metadata=prompt.usage_metadata("code_change_analysis"),
    )


def code_change_analyzer_prompt() -> PromptFile:
    return load_prompt_file(
        CODE_CHANGE_ANALYZER_PROMPT_PATH,
        version=CODE_CHANGE_ANALYZER_PROMPT_VERSION,
    )
