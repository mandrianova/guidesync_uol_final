from __future__ import annotations

from guidesync_agent.prompts.loader import PromptFile, load_prompt_file
from guidesync_agent.schemas import (
    AnalysisArtifactManifest,
    AnalysisArtifactRef,
    DocumentationEditPlan,
    EvidenceBundle,
)

RELEASE_NOTES_AGENT_PROMPT_VERSION = "release-notes-agent-v3"
LOCAL_RELEASE_NOTES_PROMPT_VERSION = "release-notes-local-writer-v2"
LOCAL_RELEASE_NOTES_CHUNK_PROMPT_VERSION = "release-notes-chunk-summary-v2"


def release_notes_agent_prompt() -> PromptFile:
    return load_prompt_file(
        "release_notes/agent_instructions.md",
        version=RELEASE_NOTES_AGENT_PROMPT_VERSION,
    )


def local_release_notes_prompt() -> PromptFile:
    return load_prompt_file(
        "release_notes/local_system.md",
        version=LOCAL_RELEASE_NOTES_PROMPT_VERSION,
    )


def local_release_notes_chunk_prompt() -> PromptFile:
    return load_prompt_file(
        "release_notes/chunk_summary_system.md",
        version=LOCAL_RELEASE_NOTES_CHUNK_PROMPT_VERSION,
    )


RELEASE_NOTES_AGENT_INSTRUCTIONS = release_notes_agent_prompt().content


def build_release_notes_task_prompt(
    goal: str,
    audience: str,
    evidence: EvidenceBundle,
    analysis_manifest: AnalysisArtifactManifest | None = None,
    edit_plan: DocumentationEditPlan | None = None,
) -> str:
    profile_line = (
        f"Project profile: {evidence.project_profile.id} v{evidence.project_profile.version}.\n"
        if evidence.project_profile
        else "Project profile: not available.\n"
    )
    analysis_checkpoint = build_analysis_checkpoint(analysis_manifest)
    edit_plan_instruction = build_edit_plan_instruction(edit_plan)
    return (
        f"Goal: {goal}\n"
        f"Audience: {audience}\n"
        f"{profile_line}"
        f"Evidence available: {len(evidence.commits)} commits, "
        f"{len(evidence.documentation)} product context item(s), "
        f"{len(evidence.browser_screenshots)} screenshot(s), "
        f"{len(evidence.warnings)} collection warning(s).\n"
        f"{analysis_checkpoint}"
        f"{edit_plan_instruction}"
        "Treat the compact analysis manifest as the primary code-change context. "
        "Use analysis_coverage to verify completeness. Read an individual artifact only "
        "when the compact digest lacks a specific fact needed for the draft; do not reopen "
        "every artifact. "
        "Produce one reviewable release notes draft for product users. The runtime "
        "will validate the shallow DocumentationUpdateModelOutput schema and convert "
        "it into the internal documentation update record."
    )


def build_analysis_checkpoint(analysis_manifest: AnalysisArtifactManifest | None) -> str:
    if analysis_manifest is None:
        return "Analysis checkpoint: no durable work plan manifest is available.\n"
    header = (
        f"Analysis checkpoint for plan task {analysis_manifest.plan_task_id}: "
        f"{len(analysis_manifest.planned_paths)} planned file(s), "
        f"{len(analysis_manifest.completed_unit_ids)} completed unit(s), "
        f"{len(analysis_manifest.failed_unit_ids)} failed unit(s), and "
        f"{len(analysis_manifest.artifacts)} durable artifact(s).\n"
    )
    if not analysis_manifest.artifacts:
        return header
    digest_lines = [analysis_artifact_digest_line(item) for item in analysis_manifest.artifacts]
    return f"{header}Compact analysis manifest:\n" + "\n".join(digest_lines) + "\n"


def analysis_artifact_digest_line(artifact: object) -> str:
    item = AnalysisArtifactRef.model_validate(artifact)
    digest = item.digest
    fields = [
        f"summary={bounded_text(digest.technical_summary, 500)}",
        f"impact={bounded_text(digest.product_impact, 350)}",
    ]
    optional_fields = (
        ("components", digest.affected_components),
        ("workflows", digest.affected_workflows),
        ("docs", digest.documentation_search_intents),
        ("risks", digest.risk_notes),
        ("evidence", digest.evidence_refs),
    )
    fields.extend(f"{name}={bounded_list(values)}" for name, values in optional_fields if values)
    if digest.needs_main_agent_review:
        fields.append("needs_review=true")
    return f"- id={item.id}; path={item.path}; " + "; ".join(fields)


def bounded_text(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else f"{compact[: limit - 3]}..."


def bounded_list(values: list[str], *, item_limit: int = 160, limit: int = 6) -> str:
    return " | ".join(bounded_text(value, item_limit) for value in values[:limit])


def build_edit_plan_instruction(edit_plan: DocumentationEditPlan | None) -> str:
    if edit_plan is None or not edit_plan.items:
        return "Pre-generation documentation edit plan: not available.\n"
    item = edit_plan.items[0]
    return (
        f"Pre-generation documentation edit plan {edit_plan.id}: "
        f"{item.operation.value} `{item.path}` at section `{item.heading}`. "
        "Draft proposed_update_markdown as the content for that exact planned section; "
        "the runtime, not the model, owns the target and operation.\n"
    )


def local_release_notes_system_prompt() -> str:
    return local_release_notes_prompt().content


def local_release_notes_system_prompt_metadata() -> dict[str, str]:
    return local_release_notes_prompt().usage_metadata("release_notes")


def local_release_notes_chunk_summary_system_prompt() -> str:
    return local_release_notes_chunk_prompt().content


def local_release_notes_chunk_summary_prompt_metadata() -> dict[str, str]:
    return local_release_notes_chunk_prompt().usage_metadata("release_notes_chunk")


def release_notes_agent_prompt_metadata() -> dict[str, str]:
    return release_notes_agent_prompt().usage_metadata("release_notes_agent")
