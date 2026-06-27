from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel

from guidesync_agent.llm.local_http import (
    extract_json_object,
    local_chat_payload,
    local_http_endpoint_mode,
    local_message_content,
    post_local_chat,
)
from guidesync_agent.llm.settings import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TIMEOUT_SECONDS,
)
from guidesync_agent.llm.structured_output import select_structured_output
from guidesync_agent.prompts.loader import PromptFile, load_prompt_file
from guidesync_agent.schemas import (
    AgentLoopActionType,
    AgentLoopModelAction,
    AgentLoopPromptContext,
    AgentLoopToolCall,
    ProjectProfileAgentOutput,
    ProviderConfig,
    ProviderKind,
)

PROJECT_PROFILE_ANALYZER_PROMPT_PATH = "project_profile/analyzer.md"
PROJECT_PROFILE_ANALYZER_PROMPT_VERSION = "project-profile-analyzer-v2"


class LocalHTTPProjectProfileAgentProvider:
    provider = "local_http"

    def __init__(self) -> None:
        self.base_url = os.environ.get("GUIDESYNC_PROJECT_PROFILE_AGENT_BASE_URL") or (
            os.environ.get("GUIDESYNC_LLM_BASE_URL") or DEFAULT_LLM_BASE_URL
        )
        self.model = os.environ.get("GUIDESYNC_PROJECT_PROFILE_AGENT_MODEL") or DEFAULT_LLM_MODEL
        self.timeout_seconds = int(
            os.environ.get(
                "GUIDESYNC_PROJECT_PROFILE_AGENT_TIMEOUT_SECONDS",
                str(DEFAULT_LLM_TIMEOUT_SECONDS),
            )
        )
        self.last_metadata: dict[str, Any] = {}

    def next_action(self, context: AgentLoopPromptContext) -> AgentLoopModelAction:
        prompt = project_profile_prompt()
        user = project_profile_loop_user_prompt(context)
        self.last_metadata = {
            **prompt.usage_metadata("project_profile_agent_loop"),
            **self.structured_call_metadata(ProjectProfileLoopAction, "loop_action"),
        }
        raw = self.structured_call(prompt.content, user, ProjectProfileLoopAction)
        return ProjectProfileLoopAction.model_validate(raw).to_agent_loop_action()

    def structured_call(
        self,
        system_prompt: str,
        user_prompt: str,
        output_model: type[BaseModel],
    ) -> dict[str, Any]:
        config = ProviderConfig(
            provider=ProviderKind.LOCAL_HTTP,
            model=self.model,
            base_url=self.base_url,
        )
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
            endpoint=endpoint,
        )
        return extract_json_object(local_message_content(body))

    def structured_call_metadata(
        self,
        output_model: type[BaseModel],
        stage: str,
    ) -> dict[str, str]:
        config = ProviderConfig(
            provider=ProviderKind.LOCAL_HTTP,
            model=self.model,
            base_url=self.base_url,
        )
        selection = select_structured_output(config, output_model, requires_tools=False)
        return selection.usage_metadata(f"project_profile_{stage}")


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
