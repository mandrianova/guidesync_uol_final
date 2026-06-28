from __future__ import annotations

from guidesync_agent.agent_runtime.pydantic_ai import model_settings_from_provider
from guidesync_agent.llm import factory
from guidesync_agent.llm.factory import build_pydantic_ai_model
from guidesync_agent.schemas import ProviderConfig, ProviderKind


def test_openai_compatible_model_uses_configured_timeout(monkeypatch) -> None:
    captured_client_kwargs = {}
    captured_model = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs) -> None:
            captured_client_kwargs.update(kwargs)

    class FakeOpenAIProvider:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class FakeOpenAIChatModel:
        def __init__(self, model_name, provider) -> None:
            captured_model["model_name"] = model_name
            captured_model["provider"] = provider

    monkeypatch.setattr(factory, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr(factory, "OpenAIProvider", FakeOpenAIProvider)
    monkeypatch.setattr(factory, "OpenAIChatModel", FakeOpenAIChatModel)

    model = build_pydantic_ai_model(
        ProviderConfig(
            provider=ProviderKind.PYDANTIC_AI,
            model="openai:google/gemma-4-31b-qat",
            base_url="http://host.docker.internal:1234/v1",
            timeout_seconds=17,
        )
    )

    assert isinstance(model, FakeOpenAIChatModel)
    assert captured_client_kwargs["base_url"] == "http://host.docker.internal:1234/v1"
    assert captured_client_kwargs["timeout"] == 17
    assert captured_model["model_name"] == "google/gemma-4-31b-qat"


def test_google_cloud_model_uses_google_cloud_provider(monkeypatch) -> None:
    captured_provider_kwargs = {}
    captured_model = {}

    class FakeGoogleCloudProvider:
        def __init__(self, **kwargs) -> None:
            captured_provider_kwargs.update(kwargs)

    class FakeGoogleModel:
        def __init__(self, model_name, provider) -> None:
            captured_model["model_name"] = model_name
            captured_model["provider"] = provider

    monkeypatch.setattr(factory, "GoogleCloudProvider", FakeGoogleCloudProvider)
    monkeypatch.setattr(factory, "GoogleModel", FakeGoogleModel)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "guidesync-test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "europe-west4")

    model = build_pydantic_ai_model(
        ProviderConfig(
            provider=ProviderKind.PYDANTIC_AI,
            model="google-cloud:gemini-3.5-flash",
            timeout_seconds=17,
        )
    )

    assert isinstance(model, FakeGoogleModel)
    assert captured_model["model_name"] == "gemini-3.5-flash"
    assert captured_provider_kwargs == {
        "api_key": None,
        "project": "guidesync-test-project",
        "location": "europe-west4",
        "base_url": None,
    }


def test_agent_model_settings_includes_configured_thinking() -> None:
    assert model_settings_from_provider(ProviderConfig(thinking="high")) == {"thinking": "high"}
    assert model_settings_from_provider(ProviderConfig()) is None


def test_agent_model_settings_includes_ui_generation_limits() -> None:
    assert model_settings_from_provider(
        ProviderConfig(metadata={"max_output_tokens": 2048, "temperature": 0.2})
    ) == {"max_tokens": 2048, "temperature": 0.2}
