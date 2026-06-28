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

from guidesync_agent.llm.structured_output import local_http_endpoint_mode
from guidesync_agent.schemas import LocalHTTPChatEndpoint, ProviderConfig, ProviderKind

OPENAI_COMPATIBLE_MODEL_PREFIXES = ("openai:", "openai-chat:", "openai-responses:")


def build_pydantic_ai_model(config: ProviderConfig) -> Any:
    config = pydantic_ai_generation_config(config)
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


def pydantic_ai_generation_config(config: ProviderConfig) -> ProviderConfig:
    if config.provider is not ProviderKind.LOCAL_HTTP:
        return config
    if (
        local_http_endpoint_mode(config.base_url)
        is not LocalHTTPChatEndpoint.OPENAI_CHAT_COMPLETIONS
    ):
        raise RuntimeError(
            "Local HTTP generation now requires an OpenAI-compatible /v1 endpoint so "
            "GuideSync can use the shared Pydantic AI runtime. Custom chat endpoints "
            "are only supported by the model-smoke diagnostic."
        )
    model = config.model
    if not model.startswith(OPENAI_COMPATIBLE_MODEL_PREFIXES):
        model = f"openai-chat:{model}"
    metadata = {
        **config.metadata,
        "configured_provider": config.metadata.get(
            "configured_provider",
            ProviderKind.LOCAL_HTTP.value,
        ),
        "generation_runtime": ProviderKind.PYDANTIC_AI.value,
        "endpoint_type": config.metadata.get("endpoint_type", "openai_compatible"),
    }
    return config.model_copy(
        update={
            "provider": ProviderKind.PYDANTIC_AI,
            "model": model,
            "metadata": metadata,
        }
    )
