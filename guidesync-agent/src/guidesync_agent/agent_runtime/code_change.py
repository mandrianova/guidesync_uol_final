from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from guidesync_agent.agent_runtime.code_change_constants import (
    CODE_CHANGE_ANALYZER_PROMPT_PATH,
    CODE_CHANGE_ANALYZER_PROMPT_VERSION,
)
from guidesync_agent.agent_runtime.code_change_model_usage import (
    CodeChangeModelUsageContext,
    code_change_call_id,
    provider_kind_or_none,
    record_code_change_model_usage,
)
from guidesync_agent.agent_runtime.code_change_taxonomy import (
    candidate_terms_for_terms,
    dedupe_preserve_order,
    sanitize_taxonomy_matches,
    taxonomy_matches_for_terms,
    values_for_kind,
)
from guidesync_agent.agent_runtime.model_usage import (
    sanitized_model_metadata,
)
from guidesync_agent.agent_runtime.pydantic_ai import (
    PydanticAgentRunCancelledError,
    PydanticAgentRunRequest,
    run_pydantic_agent_sync,
)
from guidesync_agent.agent_runtime.transcript_types import LLMTranscriptContext
from guidesync_agent.agent_runtime.transcripts import record_llm_transcript_from_metadata
from guidesync_agent.prompts.loader import PromptFile, load_prompt_file
from guidesync_agent.schemas import (
    AgentLoopObservation,
    CodeChangeAnalysis,
    CodeChangeAnalysisArtifact,
    CodeChangeAnalysisModelOutput,
    CodeChangeEvidenceRef,
    CodeChangeGroupAnalysisModelOutput,
    FileChangeSummary,
    KnowledgeConceptKind,
    ProjectProfileSnapshot,
    ProviderKind,
    ValidationFinding,
)
from guidesync_agent.schemas.model_roles import ModelRole
from guidesync_agent.services.code_change_agent_evidence import (
    code_change_evidence_refs_from_observations,
    combined_evidence_refs,
)
from guidesync_agent.services.code_change_analysis_output import (
    CodeChangeSummaryContext,
    annotate_change_analysis,
    summary_from_analysis,
)
from guidesync_agent.services.model_roles import provider_config_for_role
from guidesync_agent.settings import get_settings
from guidesync_agent.tools.code_change_agent import (
    initial_code_change_observations,
    register_code_change_agent_tools,
)

CODE_CHANGE_CONTEXT_PROMPT_PATH = "docs_update/code_change_runtime_context.md"
CODE_CHANGE_CONTEXT_PROMPT_VERSION = "docs-update-code-change-runtime-context-v2"


class CodeChangeAnalysisEvidence(BaseModel):
    diff: str = ""
    current_file: str = ""
    diff_truncated: bool = False
    current_file_truncated: bool = False
    evidence_refs: list[CodeChangeEvidenceRef] = Field(default_factory=list)


class CodeChangeReferenceSnippet(BaseModel):
    symbol: str
    path: str
    line_number: int = Field(ge=1)
    preview: str
    evidence_ref: str


class CodeChangeKnowledgeHit(BaseModel):
    node_id: str
    path: str | None = None
    heading: str | None = None
    matched_text: str
    score: float
    evidence_ref: str


class CodeChangeProfileContext(BaseModel):
    profile_id: str
    summary: str = ""
    project_description: str = ""
    architecture: list[str] = Field(default_factory=list)
    core_concepts: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    taxonomy_terms: list[str] = Field(default_factory=list)


class ChangeEvidenceBudget(BaseModel):
    max_files: int = Field(default=4, ge=1)
    max_diff_chars_per_file: int = Field(default=8_000, ge=1)
    max_current_file_chars: int = Field(default=4_000, ge=1)
    max_changed_symbols: int = Field(default=12, ge=1)
    max_reference_snippets: int = Field(default=12, ge=1)
    max_knowledge_hits: int = Field(default=4, ge=0)
    max_profile_terms: int = Field(default=20, ge=0)
    max_tool_result_chars: int = Field(default=16_000, ge=1)


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


class CodeChangeAnalysisGroupRequest(BaseModel):
    work_unit_id: str
    grouping_reason: str = ""
    connectivity_evidence: list[str] = Field(default_factory=list)
    changes: list[CodeChangeAnalysisRequest] = Field(min_length=1)
    changed_symbols: list[str] = Field(default_factory=list)
    related_references: list[CodeChangeReferenceSnippet] = Field(default_factory=list)
    knowledge_hits: list[CodeChangeKnowledgeHit] = Field(default_factory=list)
    evidence_budget: ChangeEvidenceBudget = Field(default_factory=ChangeEvidenceBudget)


class CodeChangeAnalysisProvider(Protocol):
    provider: str
    model: str

    def analyze(self, request: CodeChangeAnalysisRequest) -> object: ...


class CodeChangeGroupAnalysisProvider(Protocol):
    provider: str
    model: str

    def analyze_group(self, request: CodeChangeAnalysisGroupRequest) -> object: ...


class CodeChangeProviderMetadata(Protocol):
    provider: str
    model: str


@dataclass
class CodeChangeSubagentResult:
    summary: FileChangeSummary
    artifact: CodeChangeAnalysisArtifact


@dataclass
class CodeChangeGroupExecution:
    provider: CodeChangeAnalysisProvider | CodeChangeGroupAnalysisProvider
    analyses: dict[str, CodeChangeAnalysis]
    evidence_refs: list[CodeChangeEvidenceRef]
    findings_by_path: dict[str, list[ValidationFinding]]


@dataclass
class CodeChangePydanticDeps:
    request: CodeChangeAnalysisRequest
    observations: list[Any]
    tool_calls: int = 0


class CodeChangePromptRequestContext(BaseModel):
    run_id: str | None = None
    workflow_task_id: str | None = None
    project_id: str
    repository_id: str
    path: str
    status: str
    goal: str
    audience: str
    fallback_summary: FileChangeSummary
    project_profile: ProjectProfileSnapshot | None = None


class CodeChangePydanticPromptInput(BaseModel):
    change: CodeChangePromptRequestContext
    initial_observations: list[AgentLoopObservation] = Field(default_factory=list)


class CodeChangePromptEvidence(BaseModel):
    diff: str = ""
    current_file: str = ""
    diff_truncated: bool = False
    current_file_truncated: bool = False
    evidence_refs: list[str] = Field(default_factory=list)


class CodeChangeGroupPromptFile(BaseModel):
    path: str
    status: str
    fallback_summary: FileChangeSummary
    evidence: CodeChangePromptEvidence
    initial_observations: list[AgentLoopObservation] = Field(default_factory=list)


class ChangeEvidencePacket(BaseModel):
    work_unit_id: str
    grouping_reason: str = ""
    connectivity_evidence: list[str] = Field(default_factory=list)
    run_id: str | None = None
    workflow_task_id: str | None = None
    project_id: str
    repository_id: str
    goal: str
    audience: str
    profile_context: CodeChangeProfileContext | None = None
    changed_symbols: list[str] = Field(default_factory=list)
    related_references: list[CodeChangeReferenceSnippet] = Field(default_factory=list)
    knowledge_hits: list[CodeChangeKnowledgeHit] = Field(default_factory=list)
    budget: ChangeEvidenceBudget
    files: list[CodeChangeGroupPromptFile] = Field(min_length=1)


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

    def analyze_group(self, request: CodeChangeAnalysisGroupRequest) -> object:
        return {change.path: self.analyze(change) for change in request.changes}


class PydanticAICodeChangeAnalysisProvider:
    provider = ProviderKind.PYDANTIC_AI.value

    def __init__(self) -> None:
        self.config = provider_config_for_role(ModelRole.CODE_CHANGE_ANALYSIS)
        self.model = self.config.model
        self.last_metadata: dict[str, Any] = {}
        self.last_evidence_refs: list[CodeChangeEvidenceRef] = []

    def analyze(self, request: CodeChangeAnalysisRequest) -> object:
        raw = self.analyze_group(
            CodeChangeAnalysisGroupRequest(work_unit_id=request.path, changes=[request])
        )
        output = CodeChangeGroupAnalysisModelOutput.model_validate(raw)
        return next(item.to_analysis() for item in output.files if item.path == request.path)

    def analyze_group(self, request: CodeChangeAnalysisGroupRequest) -> object:
        validate_group_request(request)
        primary = request.changes[0]
        started_at = datetime.now(UTC)
        prompt = code_change_analyzer_prompt()
        context_prompt = code_change_context_prompt()
        observations_by_path = {
            change.path: initial_code_change_observations(change) for change in request.changes
        }
        initial_observations = [
            observation
            for change in request.changes
            for observation in observations_by_path[change.path]
        ]
        deps = CodeChangePydanticDeps(request=primary, observations=initial_observations)
        call_id = code_change_call_id(
            CodeChangeModelUsageContext(
                project_id=primary.project_id,
                run_id=primary.run_id,
                workflow_task_id=primary.workflow_task_id,
                repository_id=primary.repository_id,
                path=request.work_unit_id,
                provider=self.provider,
                model=self.model,
                metadata={},
                started_at=started_at,
                completed_at=started_at,
            )
        )
        user_prompt = pydantic_code_change_group_prompt(
            request,
            observations_by_path,
            context_prompt=context_prompt,
        )
        runtime_result = run_pydantic_agent_sync(
            PydanticAgentRunRequest(
                prompt=user_prompt,
                instructions=prompt.content,
                output_model=CodeChangeGroupAnalysisModelOutput,
                deps=deps,
                deps_type=CodeChangePydanticDeps,
                config=self.config,
                model_role=ModelRole.CODE_CHANGE_ANALYSIS,
                project_id=primary.project_id,
                run_id=primary.run_id,
                workflow_task_id=primary.workflow_task_id,
                model_call_id=call_id,
                token_ledger_entry_id=call_id,
                prompt_metadata=prompt.usage_metadata("code_change_analysis"),
                register_tools=register_code_change_agent_tools,
                retries=0,
                requires_tools=False,
            )
        )
        self.last_evidence_refs = code_change_evidence_refs_from_observations(
            deps.observations,
            [ref for change in request.changes for ref in change.evidence.evidence_refs],
        )
        self.last_metadata = sanitized_model_metadata(
            {
                **self.config.metadata,
                **prompt.usage_metadata("code_change_analysis"),
                **context_prompt.usage_metadata("code_change_context"),
                **runtime_result.usage,
                "model_turn_count": 1,
                "tool_call_count": deps.tool_calls,
                "initial_observations": len(initial_observations),
                "prompt_input_chars": len(user_prompt),
                "agent_runtime": "pydantic_ai",
            }
        )
        return runtime_result.output


class CodeChangePrompt(BaseModel):
    system: str
    user: str
    metadata: dict[str, str] = Field(default_factory=dict)


def analyze_code_change_with_subagent(
    request: CodeChangeAnalysisRequest,
    provider: CodeChangeAnalysisProvider | None = None,
) -> CodeChangeSubagentResult:
    return analyze_code_change_group_with_subagent(
        CodeChangeAnalysisGroupRequest(work_unit_id=request.path, changes=[request]),
        provider=provider,
    )[0]


def analyze_code_change_group_with_subagent(
    request: CodeChangeAnalysisGroupRequest,
    provider: CodeChangeAnalysisProvider | CodeChangeGroupAnalysisProvider | None = None,
) -> list[CodeChangeSubagentResult]:
    validate_group_request(request)
    provider = provider or default_code_change_analysis_provider()
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    execution = run_code_change_group_analysis(request, provider)
    completed_at = datetime.now(UTC)
    model_metadata = {
        "latency_ms": int((time.perf_counter() - started) * 1000),
        **getattr(execution.provider, "last_metadata", {}),
    }
    runtime_findings = record_group_runtime(
        request,
        execution,
        model_metadata,
        started_at,
        completed_at,
    )
    return build_group_results(request, execution, model_metadata, runtime_findings)


def run_code_change_group_analysis(
    request: CodeChangeAnalysisGroupRequest,
    provider: CodeChangeAnalysisProvider | CodeChangeGroupAnalysisProvider,
) -> CodeChangeGroupExecution:
    seed_refs = group_evidence_refs(request)
    findings_by_path = {change.path: [] for change in request.changes}
    try:
        analyses = normalize_code_change_group(provider_group_analysis(provider, request), request)
        evidence_refs = combined_evidence_refs(
            seed_refs,
            getattr(provider, "last_evidence_refs", []),
        )
        analyses = sanitize_group_analyses(request, analyses, evidence_refs, findings_by_path)
        if any(has_blocking_findings(items) for items in findings_by_path.values()):
            raise ValueError("model output failed code-change validation")
    except PydanticAgentRunCancelledError:
        raise
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
        analyses = normalize_code_change_group(fallback_provider.analyze_group(request), request)
        evidence_refs = seed_refs
        for change in request.changes:
            findings_by_path[change.path].append(fallback_finding(change, exc))
        provider = fallback_provider
    return CodeChangeGroupExecution(
        provider=provider,
        analyses=analyses,
        evidence_refs=evidence_refs,
        findings_by_path=findings_by_path,
    )


def sanitize_group_analyses(
    request: CodeChangeAnalysisGroupRequest,
    analyses: dict[str, CodeChangeAnalysis],
    evidence_refs: list[CodeChangeEvidenceRef],
    findings_by_path: dict[str, list[ValidationFinding]],
) -> dict[str, CodeChangeAnalysis]:
    sanitized: dict[str, CodeChangeAnalysis] = {}
    for change in request.changes:
        analysis, taxonomy_findings = sanitize_taxonomy_matches(
            analyses[change.path],
            change.project_profile.taxonomy if change.project_profile else None,
        )
        findings = findings_by_path[change.path]
        findings.extend(taxonomy_findings)
        findings.extend(validate_code_change_analysis(analysis, evidence_refs))
        sanitized[change.path] = analysis
    return sanitized


def record_group_runtime(
    request: CodeChangeAnalysisGroupRequest,
    execution: CodeChangeGroupExecution,
    model_metadata: dict[str, Any],
    started_at: datetime,
    completed_at: datetime,
) -> list[ValidationFinding]:
    primary = request.changes[0]
    findings: list[ValidationFinding] = []
    usage_finding = record_code_change_model_usage(
        CodeChangeModelUsageContext(
            project_id=primary.project_id,
            run_id=primary.run_id,
            workflow_task_id=primary.workflow_task_id,
            repository_id=primary.repository_id,
            path=request.work_unit_id,
            provider=execution.provider.provider,
            model=execution.provider.model,
            metadata=model_metadata,
            started_at=started_at,
            completed_at=completed_at,
        )
    )
    if usage_finding is not None:
        findings.append(usage_finding)
    transcript_request = primary.model_copy(
        update={
            "path": request.work_unit_id,
            "evidence": CodeChangeAnalysisEvidence(evidence_refs=execution.evidence_refs),
        }
    )
    transcript_finding = record_code_change_transcript(
        transcript_request,
        execution.provider,
        model_metadata,
        started_at,
        completed_at,
    )
    if transcript_finding is not None:
        findings.append(transcript_finding)
    return findings


def build_group_results(
    request: CodeChangeAnalysisGroupRequest,
    execution: CodeChangeGroupExecution,
    model_metadata: dict[str, Any],
    runtime_findings: list[ValidationFinding],
) -> list[CodeChangeSubagentResult]:
    results: list[CodeChangeSubagentResult] = []
    for index, change in enumerate(request.changes):
        findings = [
            *execution.findings_by_path[change.path],
            *(runtime_findings if index == 0 else []),
        ]
        analysis = execution.analyses[change.path]
        annotation_run_id, annotation_metadata = annotate_change_analysis(change, analysis)
        summary = summary_from_analysis(
            change,
            analysis,
            CodeChangeSummaryContext(
                provider=execution.provider.provider,
                model=execution.provider.model,
                prompt_version=CODE_CHANGE_ANALYZER_PROMPT_VERSION,
                annotation_run_id=annotation_run_id,
                annotation_metadata=annotation_metadata,
                findings=findings,
            ),
        )
        artifact = CodeChangeAnalysisArtifact(
            prompt_version=CODE_CHANGE_ANALYZER_PROMPT_VERSION,
            repository_id=change.repository_id,
            path=change.path,
            status=change.status,
            provider=execution.provider.provider,
            model=execution.provider.model,
            model_metadata=model_metadata,
            evidence_refs=execution.evidence_refs,
            analysis=analysis,
            annotation_run_id=annotation_run_id,
            validation_findings=findings,
        )
        results.append(CodeChangeSubagentResult(summary=summary, artifact=artifact))
    return results


def provider_group_analysis(
    provider: CodeChangeAnalysisProvider | CodeChangeGroupAnalysisProvider,
    request: CodeChangeAnalysisGroupRequest,
) -> object:
    analyze_group = getattr(provider, "analyze_group", None)
    if callable(analyze_group):
        return analyze_group(request)
    if len(request.changes) != 1:
        raise TypeError("Configured code-change provider does not support grouped analysis.")
    change = request.changes[0]
    analyze = getattr(provider, "analyze", None)
    if not callable(analyze):
        raise TypeError("Configured code-change provider cannot analyze a single change.")
    return {change.path: analyze(change)}


def normalize_code_change_group(
    raw_analysis: object,
    request: CodeChangeAnalysisGroupRequest,
) -> dict[str, CodeChangeAnalysis]:
    raw_by_path: dict[str, object]
    expected_paths = {change.path for change in request.changes}
    if isinstance(raw_analysis, dict) and set(raw_analysis) == expected_paths:
        raw_by_path = {str(path): value for path, value in raw_analysis.items()}
    else:
        output = CodeChangeGroupAnalysisModelOutput.model_validate(raw_analysis)
        raw_by_path = {item.path: item.to_analysis() for item in output.files}
        if set(raw_by_path) != expected_paths or len(raw_by_path) != len(output.files):
            raise ValueError("Grouped code-change output must cover every input path exactly once.")
    return {
        change.path: normalize_code_change_analysis(raw_by_path[change.path], change)
        for change in request.changes
    }


def group_evidence_refs(request: CodeChangeAnalysisGroupRequest) -> list[CodeChangeEvidenceRef]:
    return combined_evidence_refs(
        [
            CodeChangeEvidenceRef(
                source=snippet.evidence_ref,
                detail=f"Preloaded reference for changed symbol {snippet.symbol}.",
            )
            for snippet in request.related_references
        ]
        + [
            CodeChangeEvidenceRef(
                source=hit.evidence_ref,
                detail="Preloaded knowledge-base match for the cohesive change.",
            )
            for hit in request.knowledge_hits
        ],
        [ref for change in request.changes for ref in change.evidence.evidence_refs],
    )


def fallback_finding(
    request: CodeChangeAnalysisRequest,
    error: Exception,
) -> ValidationFinding:
    return ValidationFinding(
        severity="warning",
        check="code-change-analysis.fallback",
        message=f"Model-backed change analysis fell back to deterministic output: {error}",
        evidence_refs=[ref.source for ref in request.evidence.evidence_refs],
    )


def normalize_code_change_analysis(
    raw_analysis: object,
    request: CodeChangeAnalysisRequest,
) -> CodeChangeAnalysis:
    if isinstance(raw_analysis, CodeChangeAnalysis):
        return raw_analysis
    output = CodeChangeAnalysisModelOutput.model_validate(raw_analysis)
    evidence_refs = [ref.source for ref in request.evidence.evidence_refs]
    taxonomy = request.project_profile.taxonomy if request.project_profile else None
    model_terms = dedupe_preserve_order(
        [
            *output.taxonomy_matches,
            *output.affected_components,
            *output.affected_workflows,
            *output.key_terms_from_code,
        ]
    )
    matches = taxonomy_matches_for_terms(model_terms, taxonomy, request.evidence.evidence_refs)
    candidates = candidate_terms_for_terms(
        dedupe_preserve_order(
            [
                *output.candidate_taxonomy_updates,
                *output.key_terms_from_code,
            ]
        ),
        taxonomy,
        request.evidence.evidence_refs,
    )
    return CodeChangeAnalysis(
        what_changed=output.what_changed,
        technical_summary=output.technical_summary,
        user_or_product_impact=output.user_or_product_impact,
        affected_components=dedupe_preserve_order(
            [
                *output.affected_components,
                *values_for_kind(matches, KnowledgeConceptKind.COMPONENT),
            ]
        ),
        affected_workflows=dedupe_preserve_order(
            [
                *output.affected_workflows,
                *values_for_kind(matches, KnowledgeConceptKind.WORKFLOW),
            ]
        ),
        documentation_search_intents=output.documentation_search_intents,
        taxonomy_matches=matches,
        candidate_taxonomy_updates=candidates,
        key_terms_from_code=output.key_terms_from_code,
        needs_screenshot_check=output.needs_screenshot_check,
        uncertainty_notes=output.uncertainty_notes,
        evidence_refs=output.evidence_refs or evidence_refs,
        needs_main_agent_review=output.needs_main_agent_review,
    )


def record_code_change_transcript(
    request: CodeChangeAnalysisRequest,
    provider: CodeChangeProviderMetadata,
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
            LLMTranscriptContext(
                project_id=request.project_id,
                run_id=request.run_id,
                workflow_task_id=request.workflow_task_id,
                model_role=ModelRole.CODE_CHANGE_ANALYSIS,
                provider=provider_kind,
                model=provider.model,
                metadata=metadata,
                started_at=started_at,
                model_call_id=call_id,
                token_ledger_entry_id=call_id,
                endpoint_type=(
                    metadata.get("endpoint_type")
                    if isinstance(metadata.get("endpoint_type"), str)
                    else None
                ),
            ),
            completed_at=completed_at,
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
    configured = get_settings().models.code_change.provider or "pydantic_ai"
    if configured in {"deterministic", "fake", "fixture"}:
        return DeterministicCodeChangeAnalysisProvider()
    return PydanticAICodeChangeAnalysisProvider()


def pydantic_code_change_prompt(
    request: CodeChangeAnalysisRequest,
    _prompt: PromptFile,
    observations: list[Any],
    context_prompt: PromptFile | None = None,
) -> str:
    prompt_input = CodeChangePydanticPromptInput(
        change=CodeChangePromptRequestContext(
            run_id=request.run_id,
            workflow_task_id=request.workflow_task_id,
            project_id=request.project_id,
            repository_id=request.repository_id,
            path=request.path,
            status=request.status,
            goal=request.goal,
            audience=request.audience,
            fallback_summary=request.fallback_summary,
            project_profile=request.project_profile,
        ),
        initial_observations=[
            AgentLoopObservation.model_validate(observation) for observation in observations
        ],
    )
    prompt_file = context_prompt or code_change_context_prompt()
    return f"{prompt_file.content.rstrip()}\n\n{prompt_input.model_dump_json(indent=2)}"


def pydantic_code_change_group_prompt(
    request: CodeChangeAnalysisGroupRequest,
    observations_by_path: dict[str, list[AgentLoopObservation]],
    *,
    context_prompt: PromptFile | None = None,
) -> str:
    validate_group_request(request)
    primary = request.changes[0]
    prompt_input = ChangeEvidencePacket(
        work_unit_id=request.work_unit_id,
        grouping_reason=request.grouping_reason,
        connectivity_evidence=request.connectivity_evidence,
        run_id=primary.run_id,
        workflow_task_id=primary.workflow_task_id,
        project_id=primary.project_id,
        repository_id=primary.repository_id,
        goal=primary.goal,
        audience=primary.audience,
        profile_context=compact_profile_context(
            primary.project_profile,
            max_terms=request.evidence_budget.max_profile_terms,
        ),
        changed_symbols=request.changed_symbols,
        related_references=request.related_references,
        knowledge_hits=request.knowledge_hits,
        budget=request.evidence_budget,
        files=[
            CodeChangeGroupPromptFile(
                path=change.path,
                status=change.status,
                fallback_summary=change.fallback_summary,
                evidence=prompt_evidence(change.evidence),
                initial_observations=observations_by_path[change.path],
            )
            for change in request.changes
        ],
    )
    prompt_file = context_prompt or code_change_context_prompt()
    return f"{prompt_file.content.rstrip()}\n\n{prompt_input.model_dump_json(indent=2)}"


def prompt_evidence(evidence: CodeChangeAnalysisEvidence) -> CodeChangePromptEvidence:
    return CodeChangePromptEvidence(
        diff=evidence.diff,
        current_file=evidence.current_file,
        diff_truncated=evidence.diff_truncated,
        current_file_truncated=evidence.current_file_truncated,
        evidence_refs=[reference.source for reference in evidence.evidence_refs],
    )


def compact_profile_context(
    profile: ProjectProfileSnapshot | None,
    *,
    max_terms: int,
) -> CodeChangeProfileContext | None:
    if profile is None:
        return None
    taxonomy = profile.taxonomy
    terms = dedupe_preserve_order(
        [
            *taxonomy.categories,
            *taxonomy.components,
            *taxonomy.workflows,
            *taxonomy.documentation_areas,
            *taxonomy.domain_terms,
        ]
    )[:max_terms]
    return CodeChangeProfileContext(
        profile_id=profile.id,
        summary=profile.summary,
        project_description=profile.project_description,
        architecture=profile.architecture[:8],
        core_concepts=profile.core_concepts[:12],
        workflows=profile.workflows[:12],
        taxonomy_terms=terms,
    )


def validate_group_request(request: CodeChangeAnalysisGroupRequest) -> None:
    primary_scope = request_scope(request.changes[0])
    if any(request_scope(change) != primary_scope for change in request.changes[1:]):
        message = "Code-change group files must share one run, project, and repository scope."
        raise ValueError(message)
    paths = [change.path for change in request.changes]
    if len(paths) != len(set(paths)):
        raise ValueError("Code-change group paths must be unique.")


def request_scope(request: CodeChangeAnalysisRequest) -> tuple[str | None, ...]:
    return (
        request.run_id,
        request.workflow_task_id,
        request.project_id,
        request.repository_id,
        request.goal,
        request.audience,
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
            "evidence_refs": [ref.source for ref in request.evidence.evidence_refs],
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


def code_change_context_prompt() -> PromptFile:
    return load_prompt_file(
        CODE_CHANGE_CONTEXT_PROMPT_PATH,
        version=CODE_CHANGE_CONTEXT_PROMPT_VERSION,
    )
