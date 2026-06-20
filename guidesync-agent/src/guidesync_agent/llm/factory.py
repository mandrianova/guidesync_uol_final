from __future__ import annotations

import os
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.cohere import CohereModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.mistral import MistralModel
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.cohere import CohereProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.mistral import MistralProvider
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider

from guidesync_agent.schemas import ProviderConfig


def build_pydantic_ai_model(config: ProviderConfig) -> Any:
    model_name = config.model
    if model_name.startswith("ollama:"):
        ollama_name = model_name.split(":", maxsplit=1)[1]
        if config.base_url:
            return OllamaModel(ollama_name, provider=OllamaProvider(base_url=config.base_url))
        return model_name

    if (
        model_name.startswith("openai:")
        or model_name.startswith("openai-chat:")
        or model_name.startswith("openai-responses:")
    ):
        api_key = config.api_key or os.environ.get(config.api_key_env or "OPENAI_API_KEY", "")
        if config.base_url:
            client = AsyncOpenAI(
                base_url=config.base_url,
                api_key=api_key or "local-not-required",
                timeout=config.timeout_seconds,
            )
        else:
            client = AsyncOpenAI(api_key=api_key or None, timeout=config.timeout_seconds)
        provider = OpenAIProvider(openai_client=client)
        clean_name = model_name.split(":", maxsplit=1)[1]
        if model_name.startswith("openai-responses:"):
            return OpenAIResponsesModel(clean_name, provider=provider)
        return OpenAIChatModel(clean_name, provider=provider)

    if model_name.startswith("anthropic:"):
        clean_name = model_name.split(":", maxsplit=1)[1]
        api_key = config.api_key or os.environ.get(config.api_key_env or "ANTHROPIC_API_KEY", "")
        return AnthropicModel(
            clean_name,
            provider=AnthropicProvider(api_key=api_key or None, base_url=config.base_url),
        )

    if model_name.startswith(("google:", "google-gla:", "gemini:")):
        clean_name = model_name.split(":", maxsplit=1)[1]
        api_key = config.api_key or os.environ.get(config.api_key_env or "GOOGLE_API_KEY", "")
        return GoogleModel(
            clean_name,
            provider=GoogleProvider(api_key=api_key or None, base_url=config.base_url),
        )

    if model_name.startswith("mistral:"):
        clean_name = model_name.split(":", maxsplit=1)[1]
        api_key = config.api_key or os.environ.get(config.api_key_env or "MISTRAL_API_KEY", "")
        provider_options: dict[str, Any] = {"api_key": api_key or None}
        if config.base_url:
            provider_options["base_url"] = config.base_url
        return MistralModel(
            clean_name,
            provider=MistralProvider(**provider_options),
        )

    if model_name.startswith("cohere:"):
        clean_name = model_name.split(":", maxsplit=1)[1]
        api_key = config.api_key or os.environ.get(config.api_key_env or "COHERE_API_KEY", "")
        return CohereModel(clean_name, provider=CohereProvider(api_key=api_key or None))

    return model_name
