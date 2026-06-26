from __future__ import annotations

import pytest
from pydantic import ValidationError

from guidesync_agent.prompts.contracts import workflow_prompt_contracts
from guidesync_agent.prompts.release_notes import (
    local_release_notes_prompt,
    release_notes_agent_prompt,
)
from guidesync_agent.schemas import AgentWorkflowStep, DocumentationUpdate


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
    assert all(contract.prompt_version for contract in contracts)
    assert all(contract.output_schema_name for contract in contracts)
    assert all("properties" in contract.output_json_schema for contract in contracts)
    assert all("prompt_sha256" in contract.required_metadata for contract in contracts)


def test_release_notes_prompt_loader_exposes_metadata() -> None:
    prompt = release_notes_agent_prompt()
    local_prompt = local_release_notes_prompt()

    assert "title, summary" in prompt.content
    assert local_prompt.usage_metadata("release_notes") == {
        "release_notes_prompt_version": local_prompt.version,
        "release_notes_prompt_sha256": local_prompt.sha256,
        "release_notes_prompt_path": local_prompt.path,
    }


def test_structured_output_validation_rejects_incomplete_release_notes() -> None:
    with pytest.raises(ValidationError):
        DocumentationUpdate.model_validate({"title": "Missing required fields"})
