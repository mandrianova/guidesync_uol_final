from __future__ import annotations

import pytest
from pydantic import ValidationError

from guidesync_agent.prompts.contracts import workflow_prompt_contracts
from guidesync_agent.prompts.loader import PROMPTS_ROOT
from guidesync_agent.prompts.release_notes import (
    local_release_notes_prompt,
    release_notes_agent_prompt,
)
from guidesync_agent.schemas import AgentWorkflowStep, DocumentationUpdate, StructuredOutputMode


def test_workflow_prompt_contracts_load_files_and_schemas() -> None:
    contracts = workflow_prompt_contracts()
    steps = {contract.step for contract in contracts}

    assert {
        AgentWorkflowStep.PROJECT_PROFILE_ANALYZER,
        AgentWorkflowStep.MAIN_DOCUMENTATION_AGENT,
        AgentWorkflowStep.RETRIEVAL_REVIEWER,
        AgentWorkflowStep.CODE_CHANGE_ANALYZER,
        AgentWorkflowStep.DOCUMENTATION_EDIT_PLANNER,
        AgentWorkflowStep.DOCUMENTATION_EDITOR,
        AgentWorkflowStep.RELEASE_NOTES_WRITER,
        AgentWorkflowStep.FINAL_VALIDATOR,
    } <= steps
    assert all(len(contract.prompt_sha256) == 64 for contract in contracts)
    assert all(contract.prompt_id for contract in contracts)
    assert all(contract.prompt_version for contract in contracts)
    assert all(contract.output_schema_name for contract in contracts)
    assert all("properties" in contract.output_json_schema for contract in contracts)
    assert all("prompt_id" in contract.required_metadata for contract in contracts)
    assert all("prompt_sha256" in contract.required_metadata for contract in contracts)
    assert all("structured_output_mode" in contract.required_metadata for contract in contracts)
    assert any(
        contract.default_output_mode == StructuredOutputMode.NATIVE
        for contract in contracts
        if contract.prompt_path == "release_notes/local_system.md"
    )


def test_release_notes_prompt_loader_exposes_metadata() -> None:
    prompt = release_notes_agent_prompt()
    local_prompt = local_release_notes_prompt()

    assert "DocumentationUpdate" in prompt.content
    assert local_prompt.usage_metadata("release_notes") == {
        "release_notes_prompt_id": local_prompt.id,
        "release_notes_prompt_version": local_prompt.version,
        "release_notes_prompt_sha256": local_prompt.sha256,
        "release_notes_prompt_path": local_prompt.path,
    }


def test_prompt_files_do_not_duplicate_manual_json_shapes() -> None:
    banned_phrases = [
        "Expected JSON schema",
        "The JSON must match this object shape",
        "Return JSON only with:",
        "Return only JSON matching",
    ]

    for prompt_path in PROMPTS_ROOT.rglob("*.md"):
        content = prompt_path.read_text(encoding="utf-8")
        assert all(phrase not in content for phrase in banned_phrases), prompt_path


def test_project_profile_prompt_does_not_seed_controlled_taxonomy() -> None:
    content = (PROMPTS_ROOT / "project_profile" / "analyzer.md").read_text(encoding="utf-8")

    assert "billing, auth" not in content
    assert "release-notes, and docs" not in content
    assert "Categories are not generic tags" in content
    assert "documentation content areas" in content
    assert "Do not return `ProjectTaxonomy`" in content


def test_structured_output_validation_rejects_incomplete_release_notes() -> None:
    with pytest.raises(ValidationError):
        DocumentationUpdate.model_validate({"title": "Missing required fields"})
