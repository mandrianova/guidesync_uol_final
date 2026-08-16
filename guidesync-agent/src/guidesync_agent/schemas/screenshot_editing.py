from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class ScreenshotImageVariant(StrEnum):
    SOURCE = "source"
    DERIVATIVE = "derivative"


class ScreenshotEditKind(StrEnum):
    CROP = "crop"
    HIGHLIGHT = "highlight"
    REDACT = "redact"


class ScreenshotRegionEditMode(StrEnum):
    HIGHLIGHT = "highlight"
    REDACT = "redact"


class ScreenshotHighlightColor(StrEnum):
    YELLOW = "yellow"
    RED = "red"
    BLUE = "blue"


class ScreenshotNormalizedRegion(BaseModel):
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> ScreenshotNormalizedRegion:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("Screenshot region must stay inside normalized image bounds.")
        return self


class ScreenshotEditOperation(BaseModel):
    id: str
    kind: ScreenshotEditKind
    region: ScreenshotNormalizedRegion
    color: str | None = None
    stroke_width: int | None = Field(default=None, ge=1, le=16)
    applied_x: int = Field(ge=0)
    applied_y: int = Field(ge=0)
    applied_width: int = Field(ge=1)
    applied_height: int = Field(ge=1)


class ScreenshotEditManifest(BaseModel):
    schema_version: str = "1.0"
    renderer_version: str = "pillow-v1"
    coordinate_space: str = "normalized_top_left"
    capture_id: str
    source_artifact_name: str
    source_image_hash: str
    source_width: int = Field(ge=1)
    source_height: int = Field(ge=1)
    derivative_artifact_name: str
    derivative_image_hash: str
    derivative_width: int = Field(ge=1)
    derivative_height: int = Field(ge=1)
    operations: list[ScreenshotEditOperation] = Field(default_factory=list, max_length=12)


class ScreenshotEditToolResult(BaseModel):
    status: str = "edited"
    capture_id: str
    derivative_artifact_name: str
    manifest_artifact_name: str
    operation_count: int = Field(ge=1, le=12)
    derivative_width: int = Field(ge=1)
    derivative_height: int = Field(ge=1)
    next_action: str


class ScreenshotViewToolResult(BaseModel):
    status: str = "viewed"
    capture_id: str
    variant: ScreenshotImageVariant
    artifact_name: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    preview_width: int = Field(ge=1)
    preview_height: int = Field(ge=1)
    preview_scaled: bool
    image_hash: str
    note: str


class ScreenshotImageToolFailure(BaseModel):
    status: str = "error"
    code: str
    message: str
    next_action: str
