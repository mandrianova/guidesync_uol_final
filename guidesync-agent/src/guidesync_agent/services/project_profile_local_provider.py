from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from guidesync_agent.llm.local_http import (
    extract_json_object,
    local_chat_payload,
    local_http_endpoint_mode,
    local_message_content,
    post_local_chat,
)
from guidesync_agent.llm.structured_output import select_structured_output
from guidesync_agent.prompts.loader import PromptFile, load_prompt_file
from guidesync_agent.schemas import (
    AgentLoopActionType,
    AgentLoopModelAction,
    AgentLoopPromptContext,
    AgentLoopToolCall,
    ProjectProfileAgentOutput,
    ProviderKind,
)
from guidesync_agent.schemas.model_roles import ModelRole
from guidesync_agent.services.llm_transcripts import local_http_transcript_payload
from guidesync_agent.services.model_roles import provider_config_for_role

PROJECT_PROFILE_ANALYZER_PROMPT_PATH = "project_profile/analyzer.md"
PROJECT_PROFILE_ANALYZER_PROMPT_VERSION = "project-profile-analyzer-v2"


class LocalHTTPProjectProfileAgentProvider:
    provider = "local_http"

    def __init__(self) -> None:
        self.config = provider_config_for_role(ModelRole.PROJECT_PROFILE_FILE_READER)
        self.base_url = self.config.base_url or ""
        self.model = self.config.model
        self.timeout_seconds = self.config.timeout_seconds
        self.last_metadata: dict[str, Any] = {}
        self.transcript_exchanges: list[dict[str, Any]] = []

    def next_action(self, context: AgentLoopPromptContext) -> AgentLoopModelAction:
        prompt = project_profile_prompt()
        user = project_profile_loop_user_prompt(context)
        self.last_metadata = {
            **prompt.usage_metadata("project_profile_agent_loop"),
            **self.structured_call_metadata(ProjectProfileLoopAction, "loop_action"),
            "llm_transcript_payload": {
                "source": "local_http",
                "exchanges": self.transcript_exchanges,
                "prompt_metadata": prompt.usage_metadata("project_profile_agent_loop"),
            },
        }
        raw = self.structured_call(prompt.content, user, ProjectProfileLoopAction)
        return ProjectProfileLoopAction.model_validate(raw).to_agent_loop_action()

    def structured_call(
        self,
        system_prompt: str,
        user_prompt: str,
        output_model: type[BaseModel],
    ) -> dict[str, Any]:
        config = self.config.model_copy(update={"provider": ProviderKind.LOCAL_HTTP})
        endpoint = local_http_endpoint_mode(self.base_url)
        structured_output = select_structured_output(
            config,
            output_model,
            requires_tools=False,
        )
        payload = local_chat_payload(
            config,
            system_prompt,
            user_prompt,
            output_model=output_model,
            selection=structured_output,
            endpoint=endpoint,
        )
        body = post_local_chat(
            self.base_url,
            payload,
            self.timeout_seconds,
            config.api_key,
            endpoint=endpoint,
        )
        content = local_message_content(body)
        self.transcript_exchanges.append(
            local_http_transcript_payload(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                request_payload=payload,
                response_payload=body,
                output_text=content,
                prompt_metadata=self.structured_call_metadata(output_model, "loop_action"),
            )
        )
        self.last_metadata["llm_transcript_payload"] = {
            "source": "local_http",
            "exchanges": self.transcript_exchanges,
        }
        return extract_json_object(content)

    def structured_call_metadata(
        self,
        output_model: type[BaseModel],
        stage: str,
    ) -> dict[str, Any]:
        config = self.config.model_copy(update={"provider": ProviderKind.LOCAL_HTTP})
        selection = select_structured_output(config, output_model, requires_tools=False)
        return {
            **self.config.metadata,
            **selection.usage_metadata(f"project_profile_{stage}"),
        }


def project_profile_prompt() -> PromptFile:
    return load_prompt_file(
        PROJECT_PROFILE_ANALYZER_PROMPT_PATH,
        version=PROJECT_PROFILE_ANALYZER_PROMPT_VERSION,
    )


class ProjectProfileLoopAction(BaseModel):
    action: AgentLoopActionType
    tool_call: AgentLoopToolCall | None = None
    final_output: ProjectProfileAgentOutput | None = None
    reasoning_summary: str = ""

    def to_agent_loop_action(self) -> AgentLoopModelAction:
        return AgentLoopModelAction(
            action=self.action,
            tool_call=self.tool_call,
            final_output=(
                self.final_output.model_dump(mode="json") if self.final_output else {}
            ),
            reasoning_summary=self.reasoning_summary,
        )


def project_profile_loop_user_prompt(context: AgentLoopPromptContext) -> str:
    return json.dumps(
        {
            "task": (
                "Choose the next repository/profile tool call, or return final_output "
                "when the project profile is evidence-backed enough."
            ),
            "action_contract": {
                "tool_call": (
                    "Set action='tool_call' and provide tool_call with one available tool."
                ),
                "final": (
                    "Set action='final' and provide final_output as ProjectProfileAgentOutput."
                ),
            },
            "loop_context": context.model_dump(mode="json"),
        },
        indent=2,
    )
