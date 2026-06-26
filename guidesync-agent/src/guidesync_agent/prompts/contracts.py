from __future__ import annotations

from pydantic import BaseModel

from guidesync_agent.prompts.loader import load_prompt_file
from guidesync_agent.prompts.release_notes import (
    LOCAL_RELEASE_NOTES_PROMPT_VERSION,
    RELEASE_NOTES_AGENT_PROMPT_VERSION,
)
from guidesync_agent.schemas import (
    AgentWorkflowStep,
    CodeChangeAnalysis,
    DocumentationEditPlan,
    DocumentationEditResult,
    DocumentationUpdate,
    KnowledgeContextPack,
    ProjectProfileSnapshot,
    PromptContract,
    ValidationFindingsOutput,
)


class PromptContractDefinition(BaseModel):
    step: AgentWorkflowStep
    prompt_path: str
    prompt_version: str
    output_model: type[BaseModel]


CONTRACT_DEFINITIONS = [
    PromptContractDefinition(
        step=AgentWorkflowStep.PROJECT_PROFILE_ANALYZER,
        prompt_path="project_profile/analyzer.md",
        prompt_version="project-profile-analyzer-v2",
        output_model=ProjectProfileSnapshot,
    ),
    PromptContractDefinition(
        step=AgentWorkflowStep.MAIN_DOCUMENTATION_AGENT,
        prompt_path="docs_update/main_documentation_agent.md",
        prompt_version="docs-update-main-documentation-agent-v1",
        output_model=DocumentationUpdate,
    ),
    PromptContractDefinition(
        step=AgentWorkflowStep.RETRIEVAL_REVIEWER,
        prompt_path="docs_update/retrieval_reviewer.md",
        prompt_version="docs-update-retrieval-reviewer-v1",
        output_model=KnowledgeContextPack,
    ),
    PromptContractDefinition(
        step=AgentWorkflowStep.CODE_CHANGE_ANALYZER,
        prompt_path="docs_update/code_change_analyzer.md",
        prompt_version="docs-update-code-change-analyzer-v1",
        output_model=CodeChangeAnalysis,
    ),
    PromptContractDefinition(
        step=AgentWorkflowStep.DOCUMENTATION_EDIT_PLANNER,
        prompt_path="docs_update/documentation_edit_planner.md",
        prompt_version="docs-update-documentation-edit-planner-v1",
        output_model=DocumentationEditPlan,
    ),
    PromptContractDefinition(
        step=AgentWorkflowStep.DOCUMENTATION_EDITOR,
        prompt_path="docs_update/documentation_editor.md",
        prompt_version="docs-update-documentation-editor-v1",
        output_model=DocumentationEditResult,
    ),
    PromptContractDefinition(
        step=AgentWorkflowStep.RELEASE_NOTES_WRITER,
        prompt_path="release_notes/local_system.md",
        prompt_version=LOCAL_RELEASE_NOTES_PROMPT_VERSION,
        output_model=DocumentationUpdate,
    ),
    PromptContractDefinition(
        step=AgentWorkflowStep.FINAL_VALIDATOR,
        prompt_path="docs_update/final_validator.md",
        prompt_version="docs-update-final-validator-v1",
        output_model=ValidationFindingsOutput,
    ),
    PromptContractDefinition(
        step=AgentWorkflowStep.RELEASE_NOTES_WRITER,
        prompt_path="release_notes/agent_instructions.md",
        prompt_version=RELEASE_NOTES_AGENT_PROMPT_VERSION,
        output_model=DocumentationUpdate,
    ),
]


def workflow_prompt_contracts() -> list[PromptContract]:
    return [prompt_contract(definition) for definition in CONTRACT_DEFINITIONS]


def prompt_contract(definition: PromptContractDefinition) -> PromptContract:
    prompt = load_prompt_file(definition.prompt_path, version=definition.prompt_version)
    return PromptContract(
        step=definition.step,
        prompt_version=prompt.version,
        prompt_path=prompt.path,
        prompt_sha256=prompt.sha256,
        output_schema_name=definition.output_model.__name__,
        output_json_schema=definition.output_model.model_json_schema(),
        required_metadata=["prompt_version", "prompt_sha256", "prompt_path"],
    )
