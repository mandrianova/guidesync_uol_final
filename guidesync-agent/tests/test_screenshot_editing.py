from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from PIL import Image
from pydantic_ai import RunContext, ToolReturn
from pydantic_ai.messages import BinaryImage

from guidesync_agent.agent_runtime.pydantic_ai_context import bounded_tool_result, json_safe
from guidesync_agent.agent_runtime.transcript_payloads import sanitize_secret_value
from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    EvidenceBundle,
    ScreenshotCaptureResult,
    ScreenshotEditKind,
    ScreenshotHighlightColor,
    ScreenshotImageVariant,
    ScreenshotNormalizedRegion,
    ScreenshotPlanItem,
    ScreenshotValidationStatus,
)
from guidesync_agent.services.ui_evidence.editing import (
    MAX_MODEL_IMAGE_EDGE,
    REDACTION_COLOR,
    ScreenshotEditRequest,
    render_screenshot_derivative,
)
from guidesync_agent.settings import BrowserToolSettings
from guidesync_agent.tools.browser_evidence import replace_evidence_capture
from guidesync_agent.tools.evidence import EvidenceAgentDeps
from guidesync_agent.tools.screenshot_images import (
    edit_agent_screenshot,
    finalize_agent_screenshot_edits,
    view_agent_screenshot,
)


def test_deterministic_crop_highlight_and_redaction_preserve_source(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 80), "white").save(source)
    source_bytes = source.read_bytes()
    crop = render_screenshot_derivative(
        source,
        "capture-1",
        [],
        ScreenshotEditRequest(
            kind=ScreenshotEditKind.CROP,
            region=ScreenshotNormalizedRegion(x=0.1, y=0.25, width=0.8, height=0.5),
        ),
    )
    highlighted = render_screenshot_derivative(
        source,
        "capture-1",
        crop.manifest.operations,
        ScreenshotEditRequest(
            kind=ScreenshotEditKind.HIGHLIGHT,
            region=ScreenshotNormalizedRegion(x=0.1, y=0.1, width=0.5, height=0.5),
            color=ScreenshotHighlightColor.YELLOW.value,
            stroke_width=3,
        ),
    )
    redacted = render_screenshot_derivative(
        source,
        "capture-1",
        highlighted.manifest.operations,
        ScreenshotEditRequest(
            kind=ScreenshotEditKind.REDACT,
            region=ScreenshotNormalizedRegion(x=0.75, y=0, width=0.25, height=1),
        ),
    )
    repeated = render_screenshot_derivative(
        source,
        "capture-1",
        highlighted.manifest.operations,
        ScreenshotEditRequest(
            kind=ScreenshotEditKind.REDACT,
            region=ScreenshotNormalizedRegion(x=0.75, y=0, width=0.25, height=1),
        ),
    )

    assert source.read_bytes() == source_bytes
    assert redacted.derivative_path == repeated.derivative_path
    assert redacted.derivative_path.read_bytes() == repeated.derivative_path.read_bytes()
    assert redacted.manifest.model_dump() == repeated.manifest.model_dump()
    assert redacted.manifest.source_width == 100
    assert redacted.manifest.source_height == 80
    assert (redacted.manifest.derivative_width, redacted.manifest.derivative_height) == (80, 40)
    assert [item.kind for item in redacted.manifest.operations] == [
        ScreenshotEditKind.CROP,
        ScreenshotEditKind.HIGHLIGHT,
        ScreenshotEditKind.REDACT,
    ]
    with Image.open(redacted.derivative_path) as derivative:
        rgba = derivative.convert("RGBA")
        assert rgba.getpixel((8, 4)) == (250, 204, 21, 255)
        assert rgba.getpixel((20, 10)) == (255, 255, 255, 255)
        assert rgba.getpixel((70, 20)) == (31, 41, 55, 255)
    assert redacted.manifest.operations[-1].color == REDACTION_COLOR
    manifest = json.loads(redacted.manifest_path.read_text(encoding="utf-8"))
    assert manifest["derivative_image_hash"] == hashlib.sha256(
        redacted.derivative_path.read_bytes()
    ).hexdigest()


def test_screenshot_tools_scope_view_and_edit_to_current_session(tmp_path: Path) -> None:
    source = tmp_path / "prepared.png"
    Image.new("RGB", (120, 80), "white").save(source)
    source_bytes = source.read_bytes()
    capture = screenshot_capture(source)
    deps = EvidenceAgentDeps(
        evidence=EvidenceBundle(browser_screenshots=[capture]),
        browser=BrowserToolSettings(screenshot_dir=tmp_path),
        screenshot_session_capture_ids={"capture-1"},
    )
    context = cast(RunContext[EvidenceAgentDeps], SimpleNamespace(deps=deps))

    viewed = view_agent_screenshot(
        context,
        "capture-1",
        variant=ScreenshotImageVariant.SOURCE,
    )
    denied = view_agent_screenshot(
        context,
        "capture-from-old-task",
        variant=ScreenshotImageVariant.SOURCE,
    )
    edited = edit_agent_screenshot(
        context,
        "capture-1",
        kind=ScreenshotEditKind.CROP,
        x=0.1,
        y=0.1,
        width=0.8,
        height=0.8,
    )

    assert isinstance(viewed, ToolReturn)
    viewed_value = cast(dict[str, object], viewed.return_value)
    assert viewed_value["status"] == "viewed"
    assert viewed_value["preview_scaled"] is False
    assert any(isinstance(item, BinaryImage) for item in viewed.content or [])
    denied_value = cast(dict[str, object], denied.return_value)
    assert denied_value["code"] == "capture_out_of_scope"
    assert edited["status"] == "edited"
    updated = deps.evidence.browser_screenshots[0]
    assert updated.path == str(source)
    assert updated.publication_approved is False
    assert updated.edit_finalized is False
    assert updated.derivative_path
    assert updated.edit_manifest_path
    assert source.read_bytes() == source_bytes


def test_view_screenshot_downscales_only_the_model_preview(tmp_path: Path) -> None:
    source = tmp_path / "prepared.png"
    Image.new("RGB", (3_200, 1_800), "white").save(source)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    deps = EvidenceAgentDeps(
        evidence=EvidenceBundle(browser_screenshots=[screenshot_capture(source)]),
        browser=BrowserToolSettings(screenshot_dir=tmp_path),
        screenshot_session_capture_ids={"capture-1"},
    )
    context = cast(RunContext[EvidenceAgentDeps], SimpleNamespace(deps=deps))

    viewed = view_agent_screenshot(
        context,
        "capture-1",
        variant=ScreenshotImageVariant.SOURCE,
    )

    result = cast(dict[str, object], viewed.return_value)
    binary = next(item for item in viewed.content or [] if isinstance(item, BinaryImage))
    with Image.open(BytesIO(binary.data)) as preview:
        assert preview.size == (MAX_MODEL_IMAGE_EDGE, 900)
    assert result["width"] == 3_200
    assert result["height"] == 1_800
    assert result["preview_scaled"] is True
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash


def test_finalize_edited_screenshot_reviews_derivative(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "prepared.png"
    Image.new("RGB", (100, 100), "white").save(source)
    deps = EvidenceAgentDeps(
        evidence=EvidenceBundle(browser_screenshots=[screenshot_capture(source)]),
        browser=BrowserToolSettings(screenshot_dir=tmp_path),
        screenshot_session_capture_ids={"capture-1"},
    )
    context = cast(RunContext[EvidenceAgentDeps], SimpleNamespace(deps=deps))
    edit_agent_screenshot(
        context,
        "capture-1",
        kind=ScreenshotEditKind.REDACT,
        x=0.8,
        y=0,
        width=0.2,
        height=0.2,
    )
    reviewed: dict[str, ScreenshotCaptureResult] = {}

    def fake_validate(ctx, _item, result):
        capture = ScreenshotCaptureResult.model_validate(result).model_copy(
            update={
                "validation_status": ScreenshotValidationStatus.PASSED,
                "publication_approved": True,
            }
        )
        reviewed["capture"] = capture
        replace_evidence_capture(ctx.deps.evidence, capture)
        return {"status": "captured", "capture_id": capture.capture_id}

    monkeypatch.setattr(
        "guidesync_agent.tools.screenshot_images.validate_agent_screenshot",
        fake_validate,
    )

    result = finalize_agent_screenshot_edits(context, "capture-1")

    assert result == {"status": "captured", "capture_id": "capture-1"}
    assert reviewed["capture"].path == reviewed["capture"].derivative_path
    assert reviewed["capture"].prepared_artifact_name == Path(
        reviewed["capture"].derivative_path or ""
    ).name
    assert reviewed["capture"].edit_finalized is True


def test_multimodal_tool_return_bypasses_text_truncation_and_binary_logging() -> None:
    image = BinaryImage(b"image-bytes" * 10_000, media_type="image/png")
    result = ToolReturn({"status": "viewed"}, content=[image])

    bounded, truncated = bounded_tool_result(
        result,
        tool_name="view_screenshot",
        char_limit=200,
    )
    safe = json_safe(bounded)
    sanitized = sanitize_secret_value(safe)
    serialized = json.dumps(sanitized)

    assert isinstance(bounded, ToolReturn)
    assert bounded.content and isinstance(bounded.content[0], BinaryImage)
    assert truncated is False
    assert "image-bytes" not in serialized
    assert "BINARY_CONTENT_REMOVED" in serialized


def screenshot_capture(source: Path) -> BrowserScreenshotEvidence:
    return BrowserScreenshotEvidence(
        scenario="scenario-1",
        capture_id="capture-1",
        scenario_id="scenario-1",
        change_id="change-1",
        url="https://example.com/settings",
        path=str(source),
        prepared_artifact_name=source.name,
        prepared_image_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        publication_approved=True,
        validation_status=ScreenshotValidationStatus.PASSED,
        plan_item=ScreenshotPlanItem(
            id="scenario-1",
            change_id="change-1",
            claim_id="claim-1",
            claim="The settings panel is visible.",
            route="/settings",
            requested_state="The settings panel is visible.",
            caption="Settings panel",
            alt_text="Settings panel",
        ),
    )
