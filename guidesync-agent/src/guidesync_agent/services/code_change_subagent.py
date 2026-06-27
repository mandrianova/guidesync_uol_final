from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

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
from guidesync_agent.services.code_change_agent_evidence import (
    code_change_evidence_refs_from_observations,
    combined_evidence_refs,
)
from guidesync_agent.services.code_change_agent_loop import (
    CodeChangeLoopAction,
    code_change_loop_request,
    code_change_loop_user_prompt,
    execute_code_change_tool,
    initial_code_change_observations,
)
from guidesync_agent.services.code_change_analysis_output import (
    annotate_change_analysis,
    summary_from_analysis,
)
from guidesync_agent.services.code_change_model_usage import (
    CodeChangeModelUsageContext,
    merge_local_response_usage,
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
from guidesync_agent.services.model_roles import provider_config_for_role


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

    def analyze(self, request: CodeChangeAnalysisRequest) -> object:
        prompt = code_change_analyzer_prompt()
        self.last_usage = {}
        loop_result = run_agent_loop(
            request=code_change_loop_request(request, prompt),
            provider=self,
            execute_tool=lambda call: execute_code_change_tool(request, call),
            final_output_model=CodeChangeAnalysis,
            initial_observations=initial_code_change_observations(request),
        )
        self.last_evidence_refs = code_change_evidence_refs_from_observations(
            loop_result.observations,
            request.evidence.evidence_refs,
        )
        self.last_metadata = {
            **prompt.usage_metadata("code_change_analysis"),
            **self.structured_call_metadata(CodeChangeLoopAction, "loop_action"),
            **loop_result.model_metadata,
            **self.last_usage,
            "base_url": self.base_url,
            "model_turn_count": loop_result.model_metadata.get("loop_steps", 1),
            "tool_call_count": loop_result.model_metadata.get("tool_observations", 0),
            "compaction_checkpoints": [
                checkpoint.model_dump(mode="json")
                for checkpoint in loop_result.compaction_checkpoints
            ],
        }
        return loop_result.final_output

    def next_action(self, context: AgentLoopPromptContext) -> AgentLoopModelAction:
        prompt = code_change_analyzer_prompt()
        raw = self.structured_call(
            prompt.content,
            code_change_loop_user_prompt(context),
            CodeChangeLoopAction,
        )
        return CodeChangeLoopAction.model_validate(raw).to_agent_loop_action()

    def structured_call(
        self,
        system_prompt: str,
        user_prompt: str,
        output_model: type[BaseModel],
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


def default_code_change_analysis_provider() -> CodeChangeAnalysisProvider:
    if os.environ.get("GUIDESYNC_CODE_CHANGE_ANALYSIS_PROVIDER") == "local_http":
        return LocalHTTPCodeChangeAnalysisProvider()
    return DeterministicCodeChangeAnalysisProvider()


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
