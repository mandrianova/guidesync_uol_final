from __future__ import annotations

from dataclasses import dataclass, field

from guidesync_agent.prompts.loader import PromptFile, load_prompt_file
from guidesync_agent.schemas import (
    AnalysisArtifactManifest,
    AnalysisArtifactRef,
    DocumentationEditPlan,
    EvidenceBundle,
    ScreenshotPolicy,
)

RELEASE_NOTES_AGENT_PROMPT_VERSION = "release-notes-agent-v20"
LOCAL_RELEASE_NOTES_PROMPT_VERSION = "release-notes-local-writer-v4"
LOCAL_RELEASE_NOTES_CHUNK_PROMPT_VERSION = "release-notes-chunk-summary-v3"


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


@dataclass(frozen=True)
class ReleaseNotesPromptInput:
    goal: str
    audience: str
    evidence: EvidenceBundle
    analysis_manifest: AnalysisArtifactManifest | None = None
    edit_plan: DocumentationEditPlan | None = None
    product_name: str = "GuideSync"
    locale: str = "en"
    task_interface_url: str | None = None
    screenshot_policy: ScreenshotPolicy = ScreenshotPolicy.DISABLED
    screenshot_candidate_change_ids: list[str] = field(default_factory=list)
    knowledge_context_count: int = 0
    knowledge_context_enabled: bool = True


def build_release_notes_task_prompt(prompt_input: ReleaseNotesPromptInput) -> str:
    goal = prompt_input.goal
    audience = prompt_input.audience
    evidence = prompt_input.evidence
    profile_context = project_profile_context(evidence)
    analysis_checkpoint = build_analysis_checkpoint(prompt_input.analysis_manifest)
    edit_plan_instruction = build_edit_plan_instruction(prompt_input.edit_plan)
    knowledge_instruction = knowledge_context_instruction(prompt_input)
    return (
        f"Goal: {goal}\n"
        f"Audience: {audience}\n"
        f"Product name: {prompt_input.product_name}\n"
        f"Report locale: {prompt_input.locale}\n"
        f"Screenshot policy: {prompt_input.screenshot_policy.value}\n"
        f"Task interface URL: {prompt_input.task_interface_url or 'not available'}\n"
        "Visual change IDs that may benefit from screenshot evidence: "
        f"{', '.join(prompt_input.screenshot_candidate_change_ids) or 'none identified'}\n"
        f"{profile_context}"
        f"Evidence available: {len(evidence.commits)} commits, "
        f"{len(evidence.documentation)} product context item(s), "
        f"{len(evidence.browser_screenshots)} screenshot(s), "
        f"{len(evidence.warnings)} collection warning(s).\n"
        f"{knowledge_instruction}"
        f"{analysis_checkpoint}"
        f"{edit_plan_instruction}"
        "Treat the compact analysis manifest as the primary code-change context. "
        "The deterministic coverage line already verifies completeness; do not call "
        "analysis_coverage when it reports complete coverage. If coverage is incomplete, "
        "keep the missing evidence visible and do not guess. Read an individual artifact "
        "only when the compact digest lacks a specific fact needed for the draft; do not "
        "reopen every artifact. "
        "Write every user-facing field in English, even when the source material uses "
        "another language. Do not translate product names, code identifiers, or exact UI "
        "labels that must match the English product interface. "
        "Produce one reviewable release report for product users with one change row "
        "per distinct user-facing change. The runtime "
        "will validate the shallow DocumentationUpdateModelOutput schema and convert "
        "it into the internal documentation update record."
    )


def knowledge_context_instruction(prompt_input: ReleaseNotesPromptInput) -> str:
    if not prompt_input.knowledge_context_enabled:
        return (
            "Knowledge context: disabled for this run; knowledge list/read tools are "
            "unavailable. Use the project profile and non-knowledge evidence only.\n"
        )
    if prompt_input.knowledge_context_count == 0:
        return (
            "Preselected knowledge context: no items selected; do not call knowledge "
            "tools for this report.\n"
        )
    return (
        f"Preselected knowledge context: {prompt_input.knowledge_context_count} item(s). "
        "Use list_knowledge_context to inspect the bounded manifest, then "
        "read_knowledge_context before citing or relying on one of its refs.\n"
    )


def project_profile_context(evidence: EvidenceBundle) -> str:
    profile = evidence.project_profile
    if profile is None:
        return "Project profile: not available.\n"
    lines = [
        f"Project profile {profile.id} v{profile.version} (bounded context already loaded):",
        f"- Summary: {bounded_text(profile.summary, 500) or 'not available'}",
        (
            "- Description: "
            f"{bounded_text(profile.project_description, 900) or 'not available'}"
        ),
    ]
    if profile.project_structure:
        lines.append(f"- Structure: {bounded_list(profile.project_structure, item_limit=600)}")
    if profile.architecture:
        lines.append(f"- Architecture: {bounded_list(profile.architecture, item_limit=600)}")
    if profile.core_concepts:
        lines.append(f"- Core concepts: {bounded_list(profile.core_concepts)}")
    if profile.categories:
        lines.append(f"- Documentation categories: {bounded_list(profile.categories)}")
    lines.append(
        "Use this brief directly; call summarize_evidence only when a specific required "
        "fact is absent, not to reload the same profile."
    )
    return "\n".join(lines) + "\n"


def build_analysis_checkpoint(analysis_manifest: AnalysisArtifactManifest | None) -> str:
    if analysis_manifest is None:
        return "Analysis checkpoint: no durable work plan manifest is available.\n"
    header = (
        f"Analysis checkpoint for plan task {analysis_manifest.plan_task_id}: "
        f"{len(analysis_manifest.planned_paths)} planned file(s), "
        f"{len(analysis_manifest.completed_unit_ids)} completed unit(s), "
        f"{len(analysis_manifest.failed_unit_ids)} failed unit(s), and "
        f"{len(analysis_manifest.artifacts)} durable artifact(s).\n"
        f"{analysis_coverage_line(analysis_manifest)}"
    )
    if not analysis_manifest.artifacts:
        return header
    digest_lines = [analysis_artifact_digest_line(item) for item in analysis_manifest.artifacts]
    return f"{header}Compact analysis manifest:\n" + "\n".join(digest_lines) + "\n"


def analysis_coverage_line(manifest: AnalysisArtifactManifest) -> str:
    if not manifest.planned_paths:
        return "Deterministic analysis coverage: unavailable; no planned paths recorded.\n"
    covered_paths = {
        f"{artifact.repository_id}:{artifact.path}" for artifact in manifest.artifacts
    }
    covered_planned_paths = covered_paths.intersection(manifest.planned_paths)
    missing_paths = [path for path in manifest.planned_paths if path not in covered_paths]
    complete = not missing_paths and not manifest.failed_unit_ids
    status = "complete" if complete else "incomplete"
    detail = (
        "none"
        if not missing_paths
        else bounded_list(missing_paths, item_limit=200, limit=8)
    )
    return (
        f"Deterministic analysis coverage: {status}; {len(covered_planned_paths)}/"
        f"{len(manifest.planned_paths)} planned path(s) covered; missing paths: {detail}.\n"
    )


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
