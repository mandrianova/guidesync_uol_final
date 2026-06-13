# GuideSync Agent

GuideSync Agent is the second prototype for the CM3070 final project. It keeps the useful lessons from `project/guidesync-mvp/` but starts from a cleaner architecture:

- FastAPI service boundary;
- Pydantic request/response contracts;
- Pydantic AI-compatible model execution;
- provider abstraction for hosted and local models;
- repository evidence collection;
- HTML and Markdown report rendering;
- benchmark runner for model comparison.

The important design change from the MVP is that GuideSync does **not** assemble user-facing prose from fixed phrase templates. The model is asked to generate text freely, but inside a strict structured output contract. The pipeline then validates that the output uses evidence, includes required sections, avoids technical leakage, and exposes reviewer warnings.

## Local Setup

```bash
cd project/guidesync-agent
uv sync
```

## Run API

```bash
uv run guidesync-agent-api --host 127.0.0.1 --port 8770
```

Useful endpoints:

- `GET /health`
- `POST /runs`
- `GET /runs/{run_id}`

## Run One Fixture From CLI

```bash
uv run guidesync-agent-run fixtures/domain-guide-task.json
```

## Run Benchmarks

```bash
uv run guidesync-agent-benchmark fixtures/benchmark-suite.json
```

The default fixture uses the deterministic `mock` provider so the pipeline can be tested without API keys. Hosted and local models can be added through provider config.

## Provider Config

Example hosted provider:

```json
{
  "provider": "pydantic_ai",
  "model": "openai:gpt-5.2",
  "api_key_env": "OPENAI_API_KEY"
}
```

Example local provider using an OpenAI-compatible local endpoint:

```json
{
  "provider": "pydantic_ai",
  "model": "openai:local-model",
  "base_url": "http://127.0.0.1:11434/v1",
  "api_key_env": "LOCAL_MODEL_API_KEY"
}
```

The exact local endpoint depends on the backend, for example Ollama, llama.cpp server, vLLM, or another OpenAI-compatible server.
