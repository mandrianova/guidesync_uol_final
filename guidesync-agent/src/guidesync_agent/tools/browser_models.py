from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from guidesync_agent.schemas import EvidenceBundle, OperationError


class BrowserCaptureErrorCode(StrEnum):
    DISABLED = "browser_disabled"
    URL_REQUIRED = "browser_url_required"
    PLAYWRIGHT_UNAVAILABLE = "playwright_unavailable"
    BROWSER_UNAVAILABLE = "browser_unavailable"
    CAPTURE_FAILED = "browser_capture_failed"
    PROCESS_FAILED = "browser_process_failed"


class BrowserCaptureFailure(BaseModel):
    error: OperationError


@dataclass(frozen=True)
class BrowserScreenshotRequest:
    scenario: str
    url: str | None = None
    steps: list[str] = field(default_factory=list)
    width: int = 1440
    height: int = 1000
    expected_text: list[str] = field(default_factory=list)
    attempt: int = 1


@dataclass(frozen=True)
class BrowserCaptureContext:
    evidence: EvidenceBundle
    scenario: str
    target_url: str
    path: Path
    steps: list[str]
    width: int
    height: int
    timeout_ms: int
    expected_text: list[str]
    browser_binary: Path | None = None

    @property
    def viewport(self) -> dict[str, int]:
        return {"width": self.width, "height": self.height}


@dataclass(frozen=True)
class BrowserCaptureDiagnostics:
    notes: str
    title: str | None = None
    visible_text: str = ""
    console_errors: list[str] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)
