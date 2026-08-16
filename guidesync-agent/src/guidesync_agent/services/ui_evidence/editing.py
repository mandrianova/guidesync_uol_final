from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from guidesync_agent.schemas import (
    ScreenshotEditKind,
    ScreenshotEditManifest,
    ScreenshotEditOperation,
    ScreenshotNormalizedRegion,
)

MAX_SCREENSHOT_EDIT_OPERATIONS = 12
MAX_MODEL_IMAGE_EDGE = 1_600
REDACTION_COLOR = "#1f2937"
HIGHLIGHT_COLORS = {
    "blue": "#2563eb",
    "red": "#dc2626",
    "yellow": "#facc15",
}


@dataclass(frozen=True)
class ScreenshotEditRequest:
    kind: ScreenshotEditKind
    region: ScreenshotNormalizedRegion
    color: str | None = None
    stroke_width: int | None = None


@dataclass(frozen=True)
class RenderedScreenshotEdit:
    derivative_path: Path
    manifest_path: Path
    manifest: ScreenshotEditManifest


@dataclass(frozen=True)
class ModelImagePreview:
    data: bytes
    media_type: str
    width: int
    height: int
    scaled: bool


def render_screenshot_derivative(
    source_path: Path,
    capture_id: str,
    existing_operations: list[ScreenshotEditOperation],
    new_operation: ScreenshotEditRequest,
) -> RenderedScreenshotEdit:
    if len(existing_operations) >= MAX_SCREENSHOT_EDIT_OPERATIONS:
        raise ValueError(
            f"A screenshot supports at most {MAX_SCREENSHOT_EDIT_OPERATIONS} edit operations."
        )
    source_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    requests = [request_from_operation(operation) for operation in existing_operations]
    requests.append(new_operation)
    fingerprint = edit_fingerprint(source_hash, requests)
    safe_capture_id = safe_name(capture_id)
    derivative_path = source_path.parent / f"{safe_capture_id}-derivative-{fingerprint[:12]}.png"
    manifest_path = source_path.parent / f"{safe_capture_id}-edits-{fingerprint[:12]}.json"

    with Image.open(source_path) as opened:
        image = opened.convert("RGBA")
    source_width, source_height = image.size
    applied_operations: list[ScreenshotEditOperation] = []
    for index, request in enumerate(requests):
        image, operation = apply_operation(image, request, index=index)
        applied_operations.append(operation)

    derivative_bytes = png_bytes(image)
    derivative_hash = hashlib.sha256(derivative_bytes).hexdigest()
    derivative_path.write_bytes(derivative_bytes)
    derivative_width, derivative_height = image.size
    manifest = ScreenshotEditManifest(
        capture_id=capture_id,
        source_artifact_name=source_path.name,
        source_image_hash=source_hash,
        source_width=source_width,
        source_height=source_height,
        derivative_artifact_name=derivative_path.name,
        derivative_image_hash=derivative_hash,
        derivative_width=derivative_width,
        derivative_height=derivative_height,
        operations=applied_operations,
    )
    manifest_path.write_text(
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return RenderedScreenshotEdit(
        derivative_path=derivative_path,
        manifest_path=manifest_path,
        manifest=manifest,
    )


def request_from_operation(operation: ScreenshotEditOperation) -> ScreenshotEditRequest:
    return ScreenshotEditRequest(
        kind=operation.kind,
        region=operation.region,
        color=operation.color,
        stroke_width=operation.stroke_width,
    )


def edit_fingerprint(source_hash: str, operations: list[ScreenshotEditRequest]) -> str:
    payload = [
        {
            "kind": operation.kind.value,
            "region": operation.region.model_dump(mode="json"),
            "color": operation.color,
            "stroke_width": operation.stroke_width,
        }
        for operation in operations
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(source_hash.encode() + b":" + encoded).hexdigest()


def apply_operation(
    image: Image.Image,
    request: ScreenshotEditRequest,
    *,
    index: int,
) -> tuple[Image.Image, ScreenshotEditOperation]:
    left, top, right, bottom = pixel_box(request.region, image.size)
    applied_width = right - left
    applied_height = bottom - top
    if request.kind is ScreenshotEditKind.CROP:
        updated = image.crop((left, top, right, bottom))
        color = None
        stroke_width = None
    else:
        updated = image.copy()
        draw = ImageDraw.Draw(updated)
        if request.kind is ScreenshotEditKind.HIGHLIGHT:
            color = highlight_color(request.color)
            stroke_width = request.stroke_width or 4
            draw.rectangle(
                (left, top, right - 1, bottom - 1),
                fill=None,
                outline=color,
                width=stroke_width,
            )
        else:
            color = REDACTION_COLOR
            stroke_width = None
            draw.rectangle(
                (left, top, right - 1, bottom - 1),
                fill=color,
            )
    operation_id = operation_identifier(index, request)
    return updated, ScreenshotEditOperation(
        id=operation_id,
        kind=request.kind,
        region=request.region,
        color=color,
        stroke_width=stroke_width,
        applied_x=left,
        applied_y=top,
        applied_width=applied_width,
        applied_height=applied_height,
    )


def pixel_box(
    region: ScreenshotNormalizedRegion,
    size: tuple[int, int],
) -> tuple[int, int, int, int]:
    image_width, image_height = size
    left = min(max(math.floor(region.x * image_width), 0), image_width - 1)
    top = min(max(math.floor(region.y * image_height), 0), image_height - 1)
    right = min(max(math.ceil((region.x + region.width) * image_width), left + 1), image_width)
    bottom = min(
        max(math.ceil((region.y + region.height) * image_height), top + 1),
        image_height,
    )
    return left, top, right, bottom


def highlight_color(value: str | None) -> str:
    if value in HIGHLIGHT_COLORS.values():
        return value
    if value not in HIGHLIGHT_COLORS:
        raise ValueError("Highlight color must be blue, red, or yellow.")
    return HIGHLIGHT_COLORS[value]


def operation_identifier(index: int, request: ScreenshotEditRequest) -> str:
    payload = json.dumps(
        {
            "index": index,
            "kind": request.kind.value,
            "region": request.region.model_dump(mode="json"),
            "color": request.color,
            "stroke_width": request.stroke_width,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"screenshot-edit-{hashlib.sha256(payload.encode()).hexdigest()[:12]}"


def png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG", compress_level=9, optimize=False)
    return buffer.getvalue()


def model_image_preview(path: Path) -> ModelImagePreview:
    with Image.open(path) as opened:
        original_size = opened.size
        image = opened.convert("RGB")
        image.thumbnail(
            (MAX_MODEL_IMAGE_EDGE, MAX_MODEL_IMAGE_EDGE),
            Image.Resampling.LANCZOS,
        )
        preview_size = image.size
        preview_bytes = png_bytes(image)
    return ModelImagePreview(
        data=preview_bytes,
        media_type="image/png",
        width=preview_size[0],
        height=preview_size[1],
        scaled=preview_size != original_size,
    )


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "screenshot"
