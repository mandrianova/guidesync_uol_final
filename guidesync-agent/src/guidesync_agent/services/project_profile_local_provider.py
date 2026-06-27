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
    ProjectProfileAgentEvidence,
    ProjectProfileAgentOutput,
    ProjectProfileAgentRequest,
    ProjectProfileFileListing,
    ProjectProfileFileSelection,
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

    def select_files(
        self,
        request: ProjectProfileAgentRequest,
        file_listings: list[ProjectProfileFileListing],
    ) -> object:
        prompt = project_profile_prompt()
        user = json.dumps(
            {
                "task": "Select repository files and optional search queries to inspect.",
                "request": request.model_dump(mode="json"),
                "file_listings": [listing.model_dump(mode="json") for listing in file_listings],
            },
            indent=2,
        )
        self.last_metadata = {
            **prompt.usage_metadata("project_profile_selection"),
            **self.structured_call_metadata(ProjectProfileFileSelection, "selection"),
        }
        return self.structured_call(prompt.content, user, ProjectProfileFileSelection)

    def build_profile(
        self,
        request: ProjectProfileAgentRequest,
        evidence: ProjectProfileAgentEvidence,
        selection: ProjectProfileFileSelection,
    ) -> object:
        prompt = project_profile_prompt()
        user = json.dumps(
            {
                "task": "Create the final project profile from repository evidence.",
                "request": request.model_dump(mode="json"),
                "selection": selection.model_dump(mode="json"),
                "evidence": evidence.model_dump(mode="json"),
            },
            indent=2,
        )
        self.last_metadata = {
            **self.last_metadata,
            **prompt.usage_metadata("project_profile"),
            **self.structured_call_metadata(ProjectProfileAgentOutput, "profile"),
        }
        return self.structured_call(prompt.content, user, ProjectProfileAgentOutput)

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
