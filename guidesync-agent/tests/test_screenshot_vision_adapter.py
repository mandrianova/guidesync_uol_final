from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic_ai.messages import BinaryImage, TextContent

from guidesync_agent.agent_runtime.concurrency import agent_concurrency_key
from guidesync_agent.schemas import (
    ModelRole,
    ProviderConfig,
    ScreenshotCaptureResult,
    ScreenshotPlanItem,
)
from guidesync_agent.services import screenshot_validation
from guidesync_agent.services.screenshot_validation import (
    ModelBackedScreenshotVisionAdapter,
    ScreenshotVisionModelOutput,
    validate_screenshot_capture,
)


def test_default_screenshot_vision_adapter_uses_shared_pydantic_runtime(  # noqa: PLR0915
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run_pydantic_agent_sync(request: Any) -> SimpleNamespace:
        captured.update(vars(request))
        return SimpleNamespace(
            output=ScreenshotVisionModelOutput(
                visible_text="Document workflow screenshots",
                page_summary="GuideSync workflow page",
                ui_state="loaded",
                confidence=0.91,
                warnings=[],
            ),
            usage={"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
        )

    monkeypatch.setattr(
        screenshot_validation,
        "run_pydantic_agent_sync",
        fake_run_pydantic_agent_sync,
    )
    monkeypatch.setenv("GUIDESYNC_SCREENSHOT_VISION_PROVIDER", "local_http")
    monkeypatch.setenv(
        "GUIDESYNC_SCREENSHOT_VISION_BASE_URL",
        "http://127.0.0.1:1234/v1",
    )
    monkeypatch.setenv("GUIDESYNC_SCREENSHOT_VISION_MODEL", "openai-chat:vision-model")
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"\x89PNG\r\n\x1a\n")

    vision_config = screenshot_validation.provider_config_for_role(ModelRole.SCREENSHOT_VISION)
    attempt = validate_screenshot_capture(
        ScreenshotCaptureResult(
            scenario="task-interface",
            url="http://127.0.0.1:5173/#/knowledge",
            path=str(screenshot),
            visible_text="Document workflow",
            blank=False,
            plan_item=ScreenshotPlanItem(
                id="workflow-guide",
                change_id="change-workflow",
                claim_id="claim-workflow",
                claim="Users can open the updated workflow guide.",
                route="/#/knowledge",
                requested_state="The workflow guide is open.",
                caption="Updated workflow guide",
                alt_text="Open workflow guide",
            ),
        ),
        ["workflow"],
        adapter=ModelBackedScreenshotVisionAdapter(
            project_id="project-1",
            run_id="run-1",
            workflow_task_id="workflow-task-1",
            held_model_concurrency_key=agent_concurrency_key(vision_config),
        ),
    )

    assert attempt.model_role == ModelRole.SCREENSHOT_VISION
    assert attempt.provider == "local_http"
    assert attempt.model == "openai-chat:vision-model"
    assert attempt.ocr_text == "Document workflow screenshots"
    assert attempt.vision_raw_output["ui_state"] == "loaded"
    assert "base_url" not in attempt.model_metadata
    assert attempt.model_metadata["base_url_host_hash"]
    assert attempt.model_metadata["prompt_tokens"] == 11
    assert captured["output_model"] is ScreenshotVisionModelOutput
    assert captured["model_role"] == ModelRole.SCREENSHOT_VISION
    assert captured["requires_tools"] is False
    assert captured["acquire_concurrency_slot"] is False
    assert captured["project_id"] == "project-1"
    assert captured["run_id"] == "run-1"
    assert captured["workflow_task_id"] == "workflow-task-1"
    assert captured["prompt_metadata"]["screenshot_vision_prompt_id"] == (
        "screenshot_vision.evidence"
    )
    assert any(isinstance(item, TextContent) for item in captured["prompt"])
    assert any(isinstance(item, BinaryImage) for item in captured["prompt"])
    prompt_text = next(item.content for item in captured["prompt"] if isinstance(item, TextContent))
    assert "Users can open the updated workflow guide." in prompt_text
    assert "generic page presence is not sufficient evidence" in prompt_text


def test_distinct_screenshot_profile_acquires_own_concurrency_slot(monkeypatch) -> None:
    monkeypatch.setattr(
        screenshot_validation,
        "provider_config_for_role",
        lambda _role: ProviderConfig(metadata={"model_profile_id": "vision-profile"}),
    )

    adapter = ModelBackedScreenshotVisionAdapter(
        held_model_concurrency_key="profile:orchestrator-profile"
    )

    assert adapter.acquire_concurrency_slot is True
