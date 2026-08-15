from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

from guidesync_agent.agent_runtime import screenshot_capture
from guidesync_agent.agent_runtime.concurrency import agent_concurrency_key
from guidesync_agent.prompts.screenshot_capture import build_screenshot_capture_task_prompt
from guidesync_agent.schemas import (
    DocumentationUpdate,
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProviderConfig,
    ReleaseScreenshotRequest,
    RepositoryInput,
    ReviewerCheck,
    ScreenshotCaptureWorkflowInput,
    ScreenshotCaptureWorkflowResult,
)
from guidesync_agent.services.ui_evidence import workflow as screenshot_workflow


def test_screenshot_agent_reuses_held_model_concurrency_slot(
    monkeypatch,
    tmp_path,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_pydantic_agent(request: Any) -> SimpleNamespace:
        captured["request"] = request
        return SimpleNamespace(
            output="Screenshot capture complete.",
            transcript_id="llm-conv-screenshot",
            usage={},
        )

    monkeypatch.setattr(
        screenshot_capture,
        "run_pydantic_agent",
        fake_run_pydantic_agent,
    )
    monkeypatch.setattr(screenshot_capture, "record_model_call", lambda *_args: None)
    provider = ProviderConfig(metadata={"model_profile_id": "local-model"})
    request = GuideSyncRunRequest(
        run_id="run-screenshot",
        goal="Capture optional release-note screenshots.",
        provider=provider,
        repositories=[RepositoryInput(name="repo", url="https://example.com/repo.git")],
        task_interface_url="https://example.com/app/",
    )
    request.report.output_dir = tmp_path
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="completed",
        request=request,
        evidence=EvidenceBundle(),
        update=DocumentationUpdate(
            title="Release notes",
            summary="Summary",
            user_facing_change="Change",
            proposed_update_markdown="## Change",
            evidence_used=[],
            reviewer_checks=[
                ReviewerCheck(name="Review", status="required", notes="Check copy.")
            ],
            screenshot_requests=[
                ReleaseScreenshotRequest(
                    id="request-1",
                    change_id="change-1",
                    claim="The updated page is visible.",
                    purpose="Show the updated page.",
                    route_hint="/app/",
                )
            ],
        ),
    )

    result = asyncio.run(
        screenshot_capture.run_screenshot_capture_agent(
            run,
            project_id="project-1",
            workflow_task_id="workflow-task-1",
        )
    )

    deps = captured["request"].deps
    assert result == ("Screenshot capture complete.", "llm-conv-screenshot")
    assert deps.held_model_concurrency_key == agent_concurrency_key(provider)
    assert deps.screenshot_candidate_evidence_refs == {"change-1": []}


def test_terminal_screenshot_failure_keeps_completed_report_available(
    monkeypatch,
    tmp_path,
) -> None:
    request = GuideSyncRunRequest(
        run_id="run-screenshot-failed",
        goal="Keep the completed report when optional screenshots fail.",
        repositories=[RepositoryInput(name="repo", url="https://example.com/repo.git")],
        task_interface_url="https://example.com/app/",
    )
    request.report.output_dir = tmp_path
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="completed",
        request=request,
        evidence=EvidenceBundle(),
        update=DocumentationUpdate(
            title="Release notes",
            summary="Summary",
            user_facing_change="Change",
            proposed_update_markdown="## Change",
            evidence_used=[],
            reviewer_checks=[],
        ),
    )
    observed: dict[str, Any] = {}
    monkeypatch.setattr(
        screenshot_workflow,
        "create_run_store",
        lambda: SimpleNamespace(get=lambda _run_id: run),
    )
    monkeypatch.setattr(
        screenshot_workflow,
        "persist_screenshot_result",
        lambda current, *, warning: observed.update(run=current, warning=warning),
    )
    task = ProjectWorkflowTask(
        project_id="project-1",
        kind=ProjectWorkflowTaskKind.SCREENSHOT_CAPTURE,
        input=ScreenshotCaptureWorkflowInput(run_id=run.run_id),
        error_message="Browser timed out.",
    )

    screenshot_workflow.fail_screenshot_capture(task, retrying=False)

    assert observed["run"].status == "completed"
    assert "remains available without screenshots" in observed["warning"]


def test_screenshot_capture_exposes_and_logs_no_capture_reason(
    monkeypatch,
    tmp_path,
    caplog,
) -> None:
    request = GuideSyncRunRequest(
        run_id="run-screenshot-no-capture",
        goal="Explain why optional screenshots were not added.",
        repositories=[RepositoryInput(name="repo", url="https://example.com/repo.git")],
        task_interface_url="https://example.com/app/",
    )
    request.report.output_dir = tmp_path
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="completed",
        request=request,
        evidence=EvidenceBundle(),
        update=DocumentationUpdate(
            title="Release notes",
            summary="Summary",
            user_facing_change="Change",
            proposed_update_markdown="## Change",
            evidence_used=[],
            reviewer_checks=[],
            screenshot_requests=[
                ReleaseScreenshotRequest(
                    id="request-1",
                    change_id="change-1",
                    claim="The updated page is visible.",
                    purpose="Show the updated page.",
                    route_hint="/app/",
                )
            ],
        ),
    )
    reason = "The configured session redirected to the login origin."
    observed: dict[str, Any] = {}

    async def fake_capture(*_args, **_kwargs) -> tuple[str, str]:
        return reason, "llm-conv-no-capture"

    monkeypatch.setattr(screenshot_workflow, "require_screenshot_run", lambda _id: run)
    monkeypatch.setattr(screenshot_workflow, "run_screenshot_capture_agent", fake_capture)
    monkeypatch.setattr(
        screenshot_workflow,
        "persist_screenshot_result",
        lambda current, *, warning: observed.update(run=current, warning=warning),
    )
    task = ProjectWorkflowTask(
        project_id="project-1",
        kind=ProjectWorkflowTaskKind.SCREENSHOT_CAPTURE,
        input=ScreenshotCaptureWorkflowInput(run_id=run.run_id),
    )

    with caplog.at_level(logging.ERROR):
        completed = asyncio.run(screenshot_workflow.execute_screenshot_capture(task))

    result = ScreenshotCaptureWorkflowResult.model_validate(completed.result)
    assert result.summary == reason
    assert reason in completed.warnings[0]
    assert reason in observed["warning"]
    assert reason in caplog.text


def test_screenshot_prompt_reports_auth_state_without_cookie_value() -> None:
    request = GuideSyncRunRequest.model_validate(
        {
            "run_id": "run-auth-prompt",
            "goal": "Capture a protected page.",
            "repositories": [{"name": "repo", "url": "https://example.com/repo.git"}],
            "task_interface_url": "https://example.com/app/",
            "task_interface_auth_mode": "override",
            "task_interface_auth_type": "cookie",
            "task_interface_auth_secret": "session=prompt-secret",
        }
    )
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="completed",
        request=request,
        evidence=EvidenceBundle(),
        update=DocumentationUpdate(
            title="Release notes",
            summary="Summary",
            user_facing_change="Change",
            proposed_update_markdown="## Change",
            evidence_used=[],
            reviewer_checks=[],
        ),
    )

    prompt = build_screenshot_capture_task_prompt(run)

    assert "preconfigured by the runtime" in prompt
    assert "prompt-secret" not in prompt
    assert "prompt-secret" not in run.model_dump_json()
