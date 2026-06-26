from __future__ import annotations

from guidesync_agent.prompts.loader import PromptFile, load_prompt_file
from guidesync_agent.schemas import DocumentationUpdate, EvidenceBundle

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


def build_release_notes_task_prompt(goal: str, audience: str, evidence: EvidenceBundle) -> str:
    return (
        f"Goal: {goal}\n"
        f"Audience: {audience}\n"
        f"Evidence available: {len(evidence.commits)} commits, "
        f"{len(evidence.documentation)} product context item(s), "
        f"{len(evidence.browser_screenshots)} screenshot(s), "
        f"{len(evidence.warnings)} collection warning(s).\n"
        "Produce one reviewable release notes draft for product users. The JSON field "
        "`proposed_update_markdown` must contain the release notes markdown.\n"
        "Expected JSON schema:\n"
        f"{DocumentationUpdate.model_json_schema()}"
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
