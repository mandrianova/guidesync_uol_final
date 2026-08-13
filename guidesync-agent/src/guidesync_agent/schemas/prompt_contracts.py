from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .provider import StructuredOutputMode
from .run import ValidationFinding


class AgentWorkflowStep(StrEnum):
    PROJECT_PROFILE_ANALYZER = "project_profile_analyzer"
    MAIN_DOCUMENTATION_AGENT = "main_documentation_agent"
    RETRIEVAL_REVIEWER = "retrieval_reviewer"
    CODE_CHANGE_ANALYZER = "code_change_analyzer"
    CHANGE_ANALYSIS_ORCHESTRATOR = "change_analysis_orchestrator"
    DOCUMENTATION_EDIT_PLANNER = "documentation_edit_planner"
    DOCUMENTATION_EDITOR = "documentation_editor"
    RELEASE_NOTES_WRITER = "release_notes_writer"
    FINAL_VALIDATOR = "final_validator"


class PromptContract(BaseModel):
    step: AgentWorkflowStep
    prompt_id: str
    prompt_version: str
    prompt_path: str
    prompt_sha256: str
    output_schema_name: str
    default_output_mode: StructuredOutputMode = StructuredOutputMode.TOOL
    supported_output_modes: list[StructuredOutputMode] = Field(default_factory=list)
    output_json_schema: dict[str, Any] = Field(default_factory=dict)
    required_metadata: list[str] = Field(default_factory=list)
    failure_mode: str = "validation_finding_or_deterministic_fallback"


class ValidationFindingsOutput(BaseModel):
    findings: list[ValidationFinding] = Field(default_factory=list)


class ValidationFindingsModelOutput(BaseModel):
    """Shallow LLM-facing validation output."""

    findings_markdown: str = ""
    error_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    evidence_refs: list[str] = Field(default_factory=list)
