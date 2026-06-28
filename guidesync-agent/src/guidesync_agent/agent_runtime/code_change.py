from __future__ import annotations

import json
import os
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
from guidesync_agent.agent_runtime.pydantic_ai import run_pydantic_agent_sync
from guidesync_agent.agent_runtime.transcripts import record_llm_transcript_from_metadata
from guidesync_agent.prompts.loader import PromptFile, load_prompt_file
from guidesync_agent.schemas import (
    AgentLoopObservation,
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
from guidesync_agent.services.code_change_agent_evidence import (
    code_change_evidence_refs_from_observations,
    combined_evidence_refs,
)
from guidesync_agent.services.code_change_analysis_output import (
    annotate_change_analysis,
    summary_from_analysis,
)
from guidesync_agent.services.model_roles import provider_config_for_role
from guidesync_agent.tools.code_change_agent import (
    initial_code_change_observations,
    register_code_change_agent_tools,
)

CODE_CHANGE_CONTEXT_PROMPT_PATH = "docs_update/code_change_runtime_context.md"
CODE_CHANGE_CONTEXT_PROMPT_VERSION = "docs-update-code-change-runtime-context-v1"


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
        context_prompt = code_change_context_prompt()
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
        user_prompt = pydantic_code_change_prompt(
            request,
            prompt,
            initial_observations,
            context_prompt=context_prompt,
        )
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


def code_change_context_prompt() -> PromptFile:
    return load_prompt_file(
        CODE_CHANGE_CONTEXT_PROMPT_PATH,
        version=CODE_CHANGE_CONTEXT_PROMPT_VERSION,
    )
