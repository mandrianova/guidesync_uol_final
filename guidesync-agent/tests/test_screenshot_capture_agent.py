from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr
from pydantic_ai import ModelRetry

from guidesync_agent.agent_runtime import screenshot_capture
from guidesync_agent.agent_runtime.concurrency import agent_concurrency_key
from guidesync_agent.prompts.screenshot_capture import build_screenshot_capture_task_prompt
from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
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
    ScreenshotRetryDisposition,
    ScreenshotValidationAttempt,
    ScreenshotValidationStatus,
    TaskInterfaceAuthMode,
    TaskInterfaceAuthType,
)
from guidesync_agent.services.ui_evidence import workflow as screenshot_workflow
from guidesync_agent.tools.evidence import EvidenceAgentDeps


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
    monkeypatch.setattr(
        screenshot_capture,
        "rehydrate_provider_credentials",
        lambda config: config,
    )
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
    assert captured["request"].config.execution_limits.request_limit == 200
    assert captured["request"].config.execution_limits.tool_calls_limit == 200
    assert captured["request"].config.execution_limits.total_timeout_seconds == 1_800


def test_screenshot_agent_requires_one_changed_retry_after_validation_failure() -> None:
    registered: dict[str, Any] = {}

    class FakeAgent:
        def tool(self, function):
            return function

        def output_validator(self, function):
            registered[function.__name__] = function
            return function

    deps = EvidenceAgentDeps(
        evidence=EvidenceBundle(),
        screenshot_candidate_change_ids=["change-1"],
        screenshot_validation_attempts={
            "change-1": [
                ScreenshotValidationAttempt(
                    status=ScreenshotValidationStatus.RETRY,
                    reasons=["semantic_mismatch"],
                    retry_recommended=True,
                    retry_disposition=ScreenshotRetryDisposition.RETRY_CAPTURE,
                    semantic_mismatches=["The detail view is not open."],
                    ui_state="The summary panel is visible.",
                )
            ]
        },
    )
    screenshot_capture.register_screenshot_capture_agent_tools(FakeAgent())
    validator = registered["require_changed_validation_retry"]

    with pytest.raises(ModelRetry, match="detail view is not open"):
        validator(SimpleNamespace(deps=deps), "Done.")

    deps.screenshot_validation_attempts["change-1"].append(
        ScreenshotValidationAttempt(
            attempt=2,
            status=ScreenshotValidationStatus.RETRY,
            reasons=["semantic_mismatch"],
            retry_recommended=True,
            retry_disposition=ScreenshotRetryDisposition.RETRY_CAPTURE,
        )
    )

    with pytest.raises(ModelRetry):
        validator(SimpleNamespace(deps=deps), "Done after first retry.")

    deps.screenshot_validation_attempts["change-1"].append(
        ScreenshotValidationAttempt(
            attempt=3,
            status=ScreenshotValidationStatus.RETRY,
            reasons=["semantic_mismatch"],
            retry_recommended=True,
            retry_disposition=ScreenshotRetryDisposition.RETRY_CAPTURE,
        )
    )

    assert validator(SimpleNamespace(deps=deps), "Done after retries.") == (
        "Done after retries."
    )


def test_screenshot_agent_does_not_retry_unavailable_live_state() -> None:
    deps = EvidenceAgentDeps(
        evidence=EvidenceBundle(),
        screenshot_candidate_change_ids=["change-1"],
        screenshot_validation_attempts={
            "change-1": [
                ScreenshotValidationAttempt(
                    status=ScreenshotValidationStatus.FAILED,
                    reasons=["semantic_mismatch"],
                    retry_recommended=False,
                    retry_disposition=ScreenshotRetryDisposition.UNAVAILABLE,
                    semantic_mismatches=["The requested tab does not exist."],
                )
            ]
        },
    )

    assert screenshot_capture.screenshot_validation_retry_feedback(deps) is None


def test_screenshot_workflow_counts_only_captures_from_current_task(
    monkeypatch,
    tmp_path,
) -> None:
    request = GuideSyncRunRequest(
        run_id="run-current-captures",
        goal="Count the current screenshot attempt.",
        repositories=[RepositoryInput(name="repo", url="https://example.com/repo.git")],
        task_interface_url="https://example.com/app/",
    )
    request.report.output_dir = tmp_path
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="completed",
        request=request,
        evidence=EvidenceBundle(
            browser_screenshots=[
                BrowserScreenshotEvidence(
                    scenario="old",
                    capture_id="capture-old",
                    change_id="change-1",
                    url="https://example.com/app/",
                    path=str(tmp_path / "old.png"),
                    validation_status=ScreenshotValidationStatus.FAILED,
                )
            ]
        ),
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
                )
            ],
        ),
    )

    async def fake_capture(*_args, **_kwargs) -> tuple[str, str]:
        run.evidence.browser_screenshots.append(
            BrowserScreenshotEvidence(
                scenario="current",
                capture_id="capture-current",
                change_id="change-1",
                url="https://example.com/app/",
                path=str(tmp_path / "current.png"),
                validation_status=ScreenshotValidationStatus.PASSED,
                publication_approved=True,
            )
        )
        return "Captured current evidence.", "llm-conv-current"

    monkeypatch.setattr(screenshot_workflow, "require_screenshot_run", lambda _id: run)
    monkeypatch.setattr(screenshot_workflow, "run_screenshot_capture_agent", fake_capture)
    monkeypatch.setattr(
        screenshot_workflow,
        "persist_screenshot_result",
        lambda *_args, **_kwargs: None,
    )
    task = ProjectWorkflowTask(
        id="workflow-task-current",
        project_id="project-1",
        kind=ProjectWorkflowTaskKind.SCREENSHOT_CAPTURE,
        input=ScreenshotCaptureWorkflowInput(run_id=run.run_id),
    )

    completed = asyncio.run(screenshot_workflow.execute_screenshot_capture(task))
    result = ScreenshotCaptureWorkflowResult.model_validate(completed.result)

    assert result.capture_count == 1
    assert result.approved_count == 1
    assert len(run.evidence.browser_screenshots) == 2


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


def test_screenshot_capture_resolves_current_project_auth(monkeypatch, tmp_path) -> None:
    request = GuideSyncRunRequest(
        run_id="project-1-run-auth",
        goal="Use the latest saved project authorization.",
        repositories=[RepositoryInput(name="repo", url="https://example.com/repo.git")],
        task_interface_url="https://example.com/app/",
        task_interface_auth_mode=TaskInterfaceAuthMode.INHERIT,
        task_interface_auth_type=TaskInterfaceAuthType.LOCAL_STORAGE,
        has_task_interface_auth=True,
    )
    request.report.output_dir = tmp_path
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="completed",
        request=request,
        evidence=EvidenceBundle(),
    )
    project = SimpleNamespace(
        task_interface_url="https://example.com/settings/",
        task_interface_auth_type=TaskInterfaceAuthType.LOCAL_STORAGE,
        task_interface_auth_secret=SecretStr('{"accessToken":"current-project-token"}'),
    )
    monkeypatch.setattr(
        screenshot_workflow,
        "create_project_store",
        lambda: SimpleNamespace(get=lambda _project_id: project),
    )

    resolved = screenshot_workflow.with_current_task_interface_auth(
        run,
        project_id="project-1",
    )

    assert run.request.task_interface_auth_secret is None
    assert resolved.request.task_interface_auth_secret is not None
    assert resolved.request.task_interface_auth_secret.get_secret_value() == (
        '{"accessToken":"current-project-token"}'
    )


def test_screenshot_capture_does_not_inherit_auth_across_origins(
    monkeypatch,
    tmp_path,
) -> None:
    request = GuideSyncRunRequest(
        run_id="project-1-cross-origin",
        goal="Do not leak project authorization.",
        repositories=[RepositoryInput(name="repo", url="https://example.com/repo.git")],
        task_interface_url="https://other.example.com/app/",
        task_interface_auth_mode=TaskInterfaceAuthMode.INHERIT,
        task_interface_auth_type=TaskInterfaceAuthType.LOCAL_STORAGE,
        has_task_interface_auth=True,
    )
    request.report.output_dir = tmp_path
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="completed",
        request=request,
        evidence=EvidenceBundle(),
    )
    project = SimpleNamespace(
        task_interface_url="https://example.com/settings/",
        task_interface_auth_type=TaskInterfaceAuthType.LOCAL_STORAGE,
        task_interface_auth_secret=SecretStr('{"accessToken":"project-token"}'),
    )
    monkeypatch.setattr(
        screenshot_workflow,
        "create_project_store",
        lambda: SimpleNamespace(get=lambda _project_id: project),
    )

    resolved = screenshot_workflow.with_current_task_interface_auth(
        run,
        project_id="project-1",
    )

    assert resolved.request.has_task_interface_auth is False
    assert resolved.request.task_interface_auth_type is None
    assert resolved.request.task_interface_auth_secret is None
