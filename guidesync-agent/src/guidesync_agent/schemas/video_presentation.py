from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import VideoPresentationPolicy


class VideoPresentationStatus(StrEnum):
    DISABLED = "disabled"
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VideoPresentationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regenerate: bool = False


class VideoPresentationModelOutput(BaseModel):
    """Shallow parallel fields returned by the release-notes model profile."""

    model_config = ConfigDict(extra="forbid")

    slide_headlines: list[str] = Field(min_length=3, max_length=6)
    slide_bodies: list[str] = Field(min_length=3, max_length=6)
    slide_narrations: list[str] = Field(min_length=3, max_length=6)
    change_ids: list[str] = Field(min_length=3, max_length=6)
    claim_ids: list[str] = Field(min_length=3, max_length=6)
    screenshot_artifact_names: list[str] = Field(min_length=3, max_length=6)

    @model_validator(mode="after")
    def validate_parallel_slide_fields(self) -> VideoPresentationModelOutput:
        lengths = {
            len(self.slide_headlines),
            len(self.slide_bodies),
            len(self.slide_narrations),
            len(self.change_ids),
            len(self.claim_ids),
            len(self.screenshot_artifact_names),
        }
        if len(lengths) != 1:
            raise ValueError("Parallel video slide fields must have equal lengths.")
        return self


class VideoPresentationSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    position: int = Field(ge=1, le=6)
    headline: str = Field(min_length=1, max_length=90)
    body: str = Field(min_length=1, max_length=320)
    narration: str = Field(min_length=1, max_length=700)
    change_id: str
    claim_id: str
    screenshot_artifact_names: list[str] = Field(default_factory=list, max_length=1)


class VideoPresentationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    prompt_version: str
    slides: list[VideoPresentationSlide] = Field(min_length=3, max_length=6)


class VideoAudioSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: str
    artifact_name: str
    duration_seconds: float = Field(gt=0)
    sha256: str = Field(min_length=64, max_length=64)


class VideoSlideArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: str
    artifact_name: str
    width: Literal[1280, 1920] = 1920
    height: Literal[720, 1080] = 1080
    sha256: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_resolution(self) -> VideoSlideArtifact:
        if (self.width, self.height) not in {(1280, 720), (1920, 1080)}:
            raise ValueError("Video slide dimensions must use a supported 16:9 resolution.")
        return self


class VideoPresentationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    plan_artifact_name: str
    transcript_artifact_name: str
    video_artifact_name: str
    slides: list[VideoSlideArtifact] = Field(min_length=3, max_length=6)
    audio_segments: list[VideoAudioSegment] = Field(min_length=3, max_length=6)
    tts_backend: Literal["sherpa-onnx"] = "sherpa-onnx"
    tts_backend_version: str
    tts_model: str
    tts_voice: str
    tts_voice_id: int = Field(ge=0)
    tts_speed: float = Field(gt=0)
    width: Literal[1280, 1920] = 1920
    height: Literal[720, 1080] = 1080
    duration_seconds: float = Field(gt=0)
    video_sha256: str = Field(min_length=64, max_length=64)
    video_codec: str
    audio_codec: str
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_resolution(self) -> VideoPresentationManifest:
        if (self.width, self.height) not in {(1280, 720), (1920, 1080)}:
            raise ValueError("Video dimensions must use a supported 16:9 resolution.")
        return self


class VideoPresentationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: VideoPresentationPolicy = VideoPresentationPolicy.DISABLED
    status: VideoPresentationStatus = VideoPresentationStatus.DISABLED
    workflow_task_id: str | None = None
    video_artifact_name: str | None = None
    manifest_artifact_name: str | None = None
    transcript_artifact_name: str | None = None
    duration_seconds: float | None = Field(default=None, gt=0)
    tts_backend: str | None = None
    tts_model: str | None = None
    tts_voice: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error_message: str | None = None
