from __future__ import annotations

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
