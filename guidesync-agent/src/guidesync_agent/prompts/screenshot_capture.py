from __future__ import annotations

from guidesync_agent.prompts.loader import PromptFile, load_prompt_file
from guidesync_agent.schemas import GuideSyncRunResult

SCREENSHOT_CAPTURE_PROMPT_VERSION = "screenshot-capture-agent-v3"


def screenshot_capture_prompt() -> PromptFile:
    return load_prompt_file(
        "screenshot_capture/agent_instructions.md",
        version=SCREENSHOT_CAPTURE_PROMPT_VERSION,
    )


def build_screenshot_capture_task_prompt(run: GuideSyncRunResult) -> str:
    update = run.update
    if update is None:
        raise ValueError("Screenshot capture requires a completed release-note draft.")
    request_lines = [
        (
            f"- request_id={item.id}; change_id={item.change_id}; claim={item.claim}; "
            f"purpose={item.purpose}; route_hint={item.route_hint or 'none'}; "
            f"evidence_refs={' | '.join(item.evidence_refs) or 'none'}"
        )
        for item in update.screenshot_requests
    ]
    change_lines = [
        f"- id={change.id}; title={change.title}; summary={change.summary}"
        for change in update.changes
    ]
    return "\n".join(
        [
            f"Product: {run.request.report.product_name}",
            f"Report locale: {run.request.report.locale.value}",
            f"Allowed UI origin: {run.request.task_interface_url}",
            (
                "Browser authentication: preconfigured by the runtime; the credential is "
                "not available to you."
                if run.request.has_task_interface_auth
                else "Browser authentication: none."
            ),
            "Screenshot requests:",
            *request_lines,
            "Reported changes:",
            *change_lines,
            "Process each request independently. Inspect the live UI before choosing a route, "
            "viewport, semantic actions, visible text, caption, and alt text. Use only the exact "
            "change ids and evidence refs above. Finish with a concise text summary; screenshot "
            "evidence is persisted by the tools, not by your final response.",
        ]
    )
