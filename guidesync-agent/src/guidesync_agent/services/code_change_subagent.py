from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from guidesync_agent.llm.local_http import (
    local_chat_payload,
    local_http_endpoint_mode,
    local_message_content,
    post_local_chat,
)
from guidesync_agent.llm.settings import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TIMEOUT_SECONDS,
)
from guidesync_agent.llm.structured_output import select_structured_output
from guidesync_agent.prompts.loader import PromptFile, load_prompt_file
from guidesync_agent.schemas import (
    CodeChangeAnalysis,
    CodeChangeAnalysisArtifact,
    CodeChangeEvidenceRef,
    FileChangeSummary,
    KnowledgeAnnotationMetadata,
    KnowledgeAnnotationSourceType,
    KnowledgeConceptKind,
    ProjectProfileSnapshot,
    ProviderConfig,
    ProviderKind,
    ValidationFinding,
)
from guidesync_agent.services.code_change_subagent_taxonomy import (
    candidate_terms_for_terms,
    dedupe_preserve_order,
    sanitize_taxonomy_matches,
    taxonomy_matches_for_terms,
    values_for_kind,
)
from guidesync_agent.services.knowledge_annotation import AnnotationInput, annotate_sources

CODE_CHANGE_ANALYZER_PROMPT_VERSION = "docs-update-code-change-analyzer-v1"
CODE_CHANGE_ANALYZER_PROMPT_PATH = "docs_update/code_change_analyzer.md"


class CodeChangeAnalysisEvidence(BaseModel):
    diff: str = ""
    current_file: str = ""
    diff_truncated: bool = False
    current_file_truncated: bool = False
    evidence_refs: list[CodeChangeEvidenceRef] = Field(default_factory=list)


class CodeChangeAnalysisRequest(BaseModel):
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
        self.base_url = os.environ.get("GUIDESYNC_CODE_CHANGE_ANALYSIS_BASE_URL") or (
            os.environ.get("GUIDESYNC_LLM_BASE_URL") or DEFAULT_LLM_BASE_URL
        )
        self.model = os.environ.get("GUIDESYNC_CODE_CHANGE_ANALYSIS_MODEL") or DEFAULT_LLM_MODEL
        self.timeout_seconds = int(
            os.environ.get(
                "GUIDESYNC_CODE_CHANGE_ANALYSIS_TIMEOUT_SECONDS",
                str(DEFAULT_LLM_TIMEOUT_SECONDS),
            )
        )
        self.last_metadata: dict[str, Any] = {}

    def analyze(self, request: CodeChangeAnalysisRequest) -> object:
        prompt = code_change_prompt(request)
        config = ProviderConfig(
            provider=ProviderKind.LOCAL_HTTP,
            model=self.model,
            base_url=self.base_url,
        )
        endpoint = local_http_endpoint_mode(self.base_url)
        structured_output = select_structured_output(
            config,
            CodeChangeAnalysis,
            requires_tools=False,
        )
        payload = local_chat_payload(
            config,
            prompt.system,
            prompt.user,
            output_model=CodeChangeAnalysis,
            selection=structured_output,
            endpoint=endpoint,
        )
        self.last_metadata = {
            **prompt.metadata,
            **structured_output.usage_metadata("code_change_analysis"),
        }
        body = post_local_chat(
            self.base_url,
            payload,
            self.timeout_seconds,
            endpoint=endpoint,
        )
        content = local_message_content(body)
        return json.loads(content)


class CodeChangePrompt(BaseModel):
    system: str
    user: str
    metadata: dict[str, str] = Field(default_factory=dict)


def analyze_code_change_with_subagent(
    request: CodeChangeAnalysisRequest,
    provider: CodeChangeAnalysisProvider | None = None,
) -> CodeChangeSubagentResult:
    provider = provider or default_code_change_analysis_provider()
    started = time.perf_counter()
    findings: list[ValidationFinding] = []
    try:
        raw_analysis = provider.analyze(request)
        analysis = CodeChangeAnalysis.model_validate(raw_analysis)
        analysis, taxonomy_findings = sanitize_taxonomy_matches(
            analysis,
            request.project_profile.taxonomy if request.project_profile else None,
        )
        findings.extend(taxonomy_findings)
        findings.extend(validate_code_change_analysis(analysis, request.evidence.evidence_refs))
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
    summary = summary_from_analysis(
        request,
        analysis,
        provider=provider,
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
        model_metadata={
            "latency_ms": int((time.perf_counter() - started) * 1000),
            **getattr(provider, "last_metadata", {}),
        },
        evidence_refs=request.evidence.evidence_refs,
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


def annotate_change_analysis(
    request: CodeChangeAnalysisRequest,
    analysis: CodeChangeAnalysis,
) -> tuple[str | None, KnowledgeAnnotationMetadata | None]:
    if request.project_profile is None:
        return None, None
    source_id = f"code-change-analysis:{request.repository_id}:{request.path}"
    bundle = annotate_sources(
        [
            AnnotationInput(
                source_type=KnowledgeAnnotationSourceType.LLM_ANALYSIS,
                source_id=source_id,
                project_id=request.project_id,
                path=request.path,
                heading="Code change analysis",
                text=analysis_text(analysis),
            )
        ],
        taxonomy=request.project_profile.taxonomy,
        taxonomy_version=request.project_profile.taxonomy.version,
    )
    metadata = bundle.metadata_by_source_id.get(source_id)
    run_id = bundle.annotation_runs[0].id if bundle.annotation_runs else None
    return run_id, metadata


def summary_from_analysis(
    request: CodeChangeAnalysisRequest,
    analysis: CodeChangeAnalysis,
    *,
    provider: CodeChangeAnalysisProvider,
    annotation_run_id: str | None,
    annotation_metadata: KnowledgeAnnotationMetadata | None,
    findings: list[ValidationFinding],
) -> FileChangeSummary:
    annotation_terms = annotation_metadata.annotation_terms if annotation_metadata else []
    keywords = dedupe_preserve_order([*analysis.key_terms_from_code, *annotation_terms])[:12]
    docs_to_search = dedupe_preserve_order(
        [*analysis.documentation_search_intents, *request.fallback_summary.docs_to_search]
    )[:12]
    risk_notes = dedupe_preserve_order(
        [
            *request.fallback_summary.risk_notes,
            *analysis.uncertainty_notes,
            *[finding.message for finding in findings],
        ]
    )
    return request.fallback_summary.model_copy(
        update={
            "technical_summary": analysis.technical_summary,
            "product_impact": analysis.user_or_product_impact,
            "documentation_keywords": keywords,
            "docs_to_search": docs_to_search,
            "risk_notes": risk_notes,
            "what_changed": analysis.what_changed,
            "affected_components": analysis.affected_components,
            "affected_workflows": analysis.affected_workflows,
            "documentation_search_intents": analysis.documentation_search_intents,
            "taxonomy_matches": analysis.taxonomy_matches,
            "candidate_taxonomy_updates": analysis.candidate_taxonomy_updates,
            "key_terms_from_code": analysis.key_terms_from_code,
            "needs_screenshot_check": analysis.needs_screenshot_check,
            "uncertainty_notes": analysis.uncertainty_notes,
            "evidence_refs": analysis.evidence_refs,
            "analysis_prompt_version": CODE_CHANGE_ANALYZER_PROMPT_VERSION,
            "analysis_provider": provider.provider,
            "analysis_model": provider.model,
            "annotation_run_id": annotation_run_id,
            "needs_main_agent_review": (
                analysis.needs_main_agent_review or request.fallback_summary.needs_main_agent_review
            ),
        }
    )


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


def analysis_text(analysis: CodeChangeAnalysis) -> str:
    return "\n".join(
        [
            analysis.what_changed,
            analysis.technical_summary,
            analysis.user_or_product_impact,
            " ".join(analysis.affected_components),
            " ".join(analysis.affected_workflows),
            " ".join(analysis.documentation_search_intents),
            " ".join(analysis.key_terms_from_code),
            " ".join(update.value for update in analysis.candidate_taxonomy_updates),
        ]
    )
