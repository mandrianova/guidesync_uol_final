from __future__ import annotations

from typing import Any

from guidesync_agent.schemas import (
    CodeChangeAnalysis,
    FileChangeSummary,
    KnowledgeAnnotationMetadata,
    KnowledgeAnnotationSourceType,
    ValidationFinding,
)
from guidesync_agent.services.knowledge_annotation import AnnotationInput, annotate_sources


def annotate_change_analysis(
    request: Any,
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
    request: Any,
    analysis: CodeChangeAnalysis,
    *,
    provider: Any,
    prompt_version: str,
    annotation_run_id: str | None,
    annotation_metadata: KnowledgeAnnotationMetadata | None,
    findings: list[ValidationFinding],
) -> FileChangeSummary:
    annotation_terms = annotation_metadata.annotation_terms if annotation_metadata else []
    keywords = dedupe_strings([*analysis.key_terms_from_code, *annotation_terms])[:12]
    docs_to_search = dedupe_strings(
        [*analysis.documentation_search_intents, *request.fallback_summary.docs_to_search]
    )[:12]
    risk_notes = dedupe_strings(
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
            "analysis_prompt_version": prompt_version,
            "analysis_provider": provider.provider,
            "analysis_model": provider.model,
            "annotation_run_id": annotation_run_id,
            "needs_main_agent_review": analysis.needs_main_agent_review
            or request.fallback_summary.needs_main_agent_review,
        }
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


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value.strip())
    return result
