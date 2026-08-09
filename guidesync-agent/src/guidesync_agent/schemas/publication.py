from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import ReportLocale


class PublicationScreenshotRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_name: str
    scenario_id: str
    caption: str
    alt_text: str
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)


class PublicationChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    claim_id: str
    title: str
    summary: str
    why_it_matters: str
    how_to_markdown: str = ""
    examples: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    screenshot: PublicationScreenshotRef | None = None
    screenshots: list[PublicationScreenshotRef] = Field(default_factory=list)


class PublicationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    locale: ReportLocale
    product_name: str
    title: str
    summary: str
    user_value: str
    release_date: date
    release_period: str | None = None
    spotlight_change_id: str | None = None
    changes: list[PublicationChange] = Field(default_factory=list)
    call_to_action: str
