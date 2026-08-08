from __future__ import annotations

from collections.abc import Callable
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
from pydantic_ai.providers.google_cloud import GoogleCloudProvider
from pydantic_ai.providers.mistral import MistralProvider
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider

from guidesync_agent.llm.settings import DEFAULT_LLM_BASE_URL
from guidesync_agent.llm.structured_output import local_http_endpoint_mode
from guidesync_agent.schemas import LocalHTTPChatEndpoint, ProviderConfig, ProviderKind
from guidesync_agent.settings import get_settings

OPENAI_COMPATIBLE_MODEL_PREFIXES = ("openai:", "openai-chat:", "openai-responses:")
GOOGLE_CLOUD_MODEL_PREFIX = "google-cloud:"


def build_pydantic_ai_model(config: ProviderConfig) -> Any:
    config = pydantic_ai_generation_config(config)
    model_name = config.model
    builders: tuple[tuple[tuple[str, ...], Callable[[ProviderConfig, str], Any]], ...] = (
        (("ollama:",), build_ollama_model),
        (OPENAI_COMPATIBLE_MODEL_PREFIXES, build_openai_model),
        (("anthropic:",), build_anthropic_model),
        (("google:", "google-gla:", "gemini:"), build_google_model),
        ((GOOGLE_CLOUD_MODEL_PREFIX,), build_google_cloud_model),
        (("mistral:",), build_mistral_model),
        (("cohere:",), build_cohere_model),
    )
    for prefixes, builder in builders:
        if model_name.startswith(prefixes):
            return builder(config, model_name.split(":", maxsplit=1)[1])
    return model_name


def build_ollama_model(config: ProviderConfig, model_name: str) -> Any:
    if not config.base_url:
        return config.model
    return OllamaModel(model_name, provider=OllamaProvider(base_url=config.base_url))


def build_openai_model(config: ProviderConfig, model_name: str) -> Any:
    api_key = provider_api_key(config, "OPENAI_API_KEY")
    if config.base_url:
        client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=api_key or "local-not-required",
            timeout=config.timeout_seconds,
        )
    else:
        client = AsyncOpenAI(api_key=api_key or None, timeout=config.timeout_seconds)
    provider = OpenAIProvider(openai_client=client)
    if config.model.startswith("openai-responses:"):
        return OpenAIResponsesModel(model_name, provider=provider)
    return OpenAIChatModel(model_name, provider=provider)


def build_anthropic_model(config: ProviderConfig, model_name: str) -> AnthropicModel:
    api_key = provider_api_key(config, "ANTHROPIC_API_KEY")
    return AnthropicModel(
        model_name,
        provider=AnthropicProvider(api_key=api_key or None, base_url=config.base_url),
    )


def build_google_model(config: ProviderConfig, model_name: str) -> GoogleModel:
    api_key = provider_api_key(config, "GOOGLE_API_KEY")
    return GoogleModel(
        model_name,
        provider=GoogleProvider(api_key=api_key or None, base_url=config.base_url),
    )


def build_google_cloud_model(config: ProviderConfig, model_name: str) -> GoogleModel:
    api_key = provider_api_key(config, "GOOGLE_API_KEY")
    google_cloud = get_settings().google_cloud
    base_url = None if config.base_url == DEFAULT_LLM_BASE_URL else config.base_url
    return GoogleModel(
        model_name,
        provider=GoogleCloudProvider(
            api_key=api_key or None,
            project=google_cloud.project,
            location=google_cloud.location,
            base_url=base_url,
        ),
    )


def build_mistral_model(config: ProviderConfig, model_name: str) -> MistralModel:
    api_key = provider_api_key(config, "MISTRAL_API_KEY")
    provider_options: dict[str, Any] = {"api_key": api_key or None}
    if config.base_url:
        provider_options["base_url"] = config.base_url
    return MistralModel(model_name, provider=MistralProvider(**provider_options))


def build_cohere_model(config: ProviderConfig, model_name: str) -> CohereModel:
    api_key = provider_api_key(config, "COHERE_API_KEY")
    return CohereModel(model_name, provider=CohereProvider(api_key=api_key or None))


def provider_api_key(config: ProviderConfig, default_environment_name: str) -> str:
    return config.api_key or get_settings().credentials.api_key(
        config.api_key_env or default_environment_name
    ) or ""


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
