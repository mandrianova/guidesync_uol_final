from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic_ai.messages import BinaryImage, TextContent

from guidesync_agent.agent_runtime.concurrency import agent_concurrency_key
from guidesync_agent.schemas import (
    ModelRole,
    ProviderConfig,
    ReportLocale,
    ScreenshotCaptureResult,
    ScreenshotPlanItem,
    ScreenshotRetryDisposition,
    ScreenshotReviewVerdict,
    ScreenshotValidationStatus,
    ScreenshotVisionResult,
)
from guidesync_agent.services.ui_evidence import validation as screenshot_validation
from guidesync_agent.services.ui_evidence.validation import (
    DeterministicScreenshotVisionAdapter,
    ModelBackedScreenshotVisionAdapter,
    ScreenshotVisionModelOutput,
    finalize_screenshot_capture,
    validate_screenshot_capture,
)


class UnavailableScreenshotVisionAdapter:
    name = "unavailable-fixture"

    def extract_text(self, capture: ScreenshotCaptureResult) -> ScreenshotVisionResult:
        return ScreenshotVisionResult(
            adapter=self.name,
            text=capture.visible_text,
            review_verdict=ScreenshotReviewVerdict.REJECT,
            confidence=0.98,
            ui_state="Billing exposes Manage plans but no Plans tab.",
            mismatches=["The requested Plans tab does not exist in this UI."],
            retry_disposition=ScreenshotRetryDisposition.UNAVAILABLE,
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
                review_verdict=ScreenshotReviewVerdict.SUPPORTED,
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
        "screenshot_vision.system"
    )
    assert any(isinstance(item, TextContent) for item in captured["prompt"])
    assert any(isinstance(item, BinaryImage) for item in captured["prompt"])
    prompt_text = next(item.content for item in captured["prompt"] if isinstance(item, TextContent))
    assert "Users can open the updated workflow guide." in prompt_text
    assert "Generic page\npresence is not proof" in captured["instructions"]


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


def test_high_confidence_unavailable_state_does_not_request_capture_retry(
    tmp_path: Path,
) -> None:
    attempt = validate_screenshot_capture(
        ScreenshotCaptureResult(
            scenario="billing",
            url="https://example.com/app/",
            path=str(tmp_path / "billing.png"),
            visible_text="Billing Manage plans No paid seats",
            requested_state="The Plans tab is visible.",
        ),
        ["Manage plans"],
        adapter=UnavailableScreenshotVisionAdapter(),
    )

    assert attempt.status is ScreenshotValidationStatus.FAILED
    assert attempt.retry_recommended is False
    assert attempt.retry_disposition is ScreenshotRetryDisposition.UNAVAILABLE


def test_locale_validation_uses_text_near_expected_target(tmp_path: Path) -> None:
    russian_background = " ".join(["Анализ годовых расходов"] * 80)
    attempt = validate_screenshot_capture(
        ScreenshotCaptureResult(
            scenario="credits",
            url="https://example.com/app/",
            path=str(tmp_path / "credits.png"),
            visible_text=(
                f"{russian_background} Billing Credits & grants $5 available "
                "5 expired Payment method"
            ),
        ),
        ["Credits & grants", "$5 available"],
        locale=ReportLocale.ENGLISH,
        adapter=DeterministicScreenshotVisionAdapter(),
    )

    assert "wrong_language" not in attempt.reasons
    assert attempt.status is ScreenshotValidationStatus.PASSED


def test_supported_with_notes_accepts_missing_secondary_text(tmp_path: Path) -> None:
    class SupportedWithNotesAdapter:
        name = "supported-with-notes-fixture"

        def extract_text(self, capture: ScreenshotCaptureResult) -> ScreenshotVisionResult:
            return ScreenshotVisionResult(
                adapter=self.name,
                text=capture.visible_text,
                review_verdict=ScreenshotReviewVerdict.SUPPORTED_WITH_NOTES,
                confidence=0.88,
                ui_state="The responsive member row is visibly rendered.",
                mismatches=["The full member name is truncated."],
            )

    screenshot = tmp_path / "team.png"
    screenshot.write_bytes(b"prepared screenshot")
    capture = ScreenshotCaptureResult(
        scenario="team-row",
        url="https://example.com/app/team",
        path=str(screenshot),
        visible_text="Margarita A... Creator Active 17.2M tokens",
    )
    attempt = validate_screenshot_capture(
        capture,
        ["Margarita Andrianova", "19 dialogs"],
        adapter=SupportedWithNotesAdapter(),
    )
    finalized = finalize_screenshot_capture(capture, [attempt])

    assert attempt.status is ScreenshotValidationStatus.PASSED
    assert attempt.review_verdict is ScreenshotReviewVerdict.SUPPORTED_WITH_NOTES
    assert "missing_expected_text" in attempt.reasons
    assert "semantic_mismatch" in attempt.reasons
    assert attempt.retry_recommended is False
    assert finalized.publication_approved is True
    assert finalized.review_verdict is ScreenshotReviewVerdict.SUPPORTED_WITH_NOTES


def test_supported_verdict_cannot_override_private_data_blocker(tmp_path: Path) -> None:
    class SupportedAdapter:
        name = "supported-fixture"

        def extract_text(self, capture: ScreenshotCaptureResult) -> ScreenshotVisionResult:
            return ScreenshotVisionResult(
                adapter=self.name,
                text=capture.visible_text,
                review_verdict=ScreenshotReviewVerdict.SUPPORTED,
                confidence=0.95,
            )

    screenshot = tmp_path / "team-private.png"
    screenshot.write_bytes(b"private screenshot")
    capture = ScreenshotCaptureResult(
        scenario="team-row-private",
        url="https://example.com/app/team",
        path=str(screenshot),
        visible_text="Margarita margo@example.com Active",
    )
    attempt = validate_screenshot_capture(
        capture,
        ["Active"],
        adapter=SupportedAdapter(),
    )
    finalized = finalize_screenshot_capture(capture, [attempt])

    assert attempt.status is ScreenshotValidationStatus.RETRY
    assert "privacy_sensitive_content" in attempt.reasons
    assert attempt.retry_recommended is True
    assert finalized.publication_approved is False
