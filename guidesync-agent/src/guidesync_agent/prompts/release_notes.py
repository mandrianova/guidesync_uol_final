from __future__ import annotations

from guidesync_agent.prompts.loader import PromptFile, load_prompt_file
from guidesync_agent.schemas import (
    AnalysisArtifactManifest,
    DocumentationEditPlan,
    EvidenceBundle,
)

RELEASE_NOTES_AGENT_PROMPT_VERSION = "release-notes-agent-v2"
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
        "Use list_analysis_artifacts, analysis_coverage, and read_analysis_artifact "
        "before drafting when analysis artifacts are available. "
        "Produce one reviewable release notes draft for product users. The runtime "
        "will validate the shallow DocumentationUpdateModelOutput schema and convert "
        "it into the internal documentation update record."
    )


def build_analysis_checkpoint(analysis_manifest: AnalysisArtifactManifest | None) -> str:
    if analysis_manifest is None:
        return "Analysis checkpoint: no durable work plan manifest is available.\n"
    return (
        f"Analysis checkpoint for plan task {analysis_manifest.plan_task_id}: "
        f"{len(analysis_manifest.planned_paths)} planned file(s), "
        f"{len(analysis_manifest.completed_unit_ids)} completed unit(s), "
        f"{len(analysis_manifest.failed_unit_ids)} failed unit(s), and "
        f"{len(analysis_manifest.artifacts)} durable artifact(s). "
        "Artifact bodies are not embedded here; inspect them with the bounded analysis tools.\n"
    )


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
