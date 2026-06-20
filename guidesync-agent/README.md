# GuideSync Agent

GuideSync Agent is the second prototype for the CM3070 final project. It keeps the useful lessons from `project/guidesync-mvp/` but starts from a cleaner architecture:

- FastAPI service boundary;
- Pydantic request/response contracts;
- Pydantic AI-compatible model execution;
- provider abstraction for hosted and local models;
- database-backed project setup for repositories and documentation context;
- repository evidence collection;
- S3-compatible report artifact storage;
- HTML, Markdown, and JSON report rendering;
- benchmark runner for model comparison.

The important design change from the MVP is that GuideSync does **not** assemble user-facing prose from fixed phrase templates. The model is asked to generate text freely, but inside a strict structured output contract. The pipeline then validates that the output uses evidence, includes required sections, avoids technical leakage, and exposes reviewer warnings.

Architecture and code-style guidance for future changes lives in
[`docs/code-style-guide.md`](docs/code-style-guide.md).

## Local Setup

```bash
cd project/guidesync-agent
uv sync
```

By default the prototype can still fall back to local JSON files under `outputs/`
for tests and manual CLI runs. The intended application path is Postgres for
project/run metadata and S3-compatible storage for generated report artifacts.

## Run With Docker Compose

```bash
cd project/guidesync-agent
docker compose up --build
```

This starts:

- `db`: Postgres with the `guidesync` database;
- `minio`: local S3-compatible storage on `http://127.0.0.1:9000`;
- `bucket-init`: creates the `guidesync-reports` bucket;
- `app`: FastAPI on `http://127.0.0.1:8770`;
- `worker`: background process that claims queued report runs from Postgres.

Published ports are bound to `127.0.0.1` for local development. The database and
MinIO are also available to the application through the internal Compose network
at `db:5432` and `minio:9000`.

## Run API

```bash
uv run guidesync-agent-api --host 127.0.0.1 --port 8770
```

In another terminal, run the worker:

```bash
uv run guidesync-agent-worker --interval 5
```

Project report creation is asynchronous. `POST /projects/{project_id}/runs`
saves a `queued` run record and returns immediately. The worker claims queued
runs, updates status to `running`, executes the pipeline, and then persists
`completed` or `failed`.

Useful endpoints:

- `GET /` browser UI for launching runs and reviewing results
- `GET /health`
- `GET /projects`
- `POST /projects`
- `PUT /projects/{project_id}`
- `POST /projects/{project_id}/runs`
- `GET /projects/{project_id}/runs`
- `POST /projects/{project_id}/knowledge/index-runs`
- `GET /projects/{project_id}/knowledge/index-runs`
- `POST /knowledge/search`
- `POST /knowledge/context-pack`
- `GET /github/branches?url=...`
- `POST /runs`
- `GET /runs`
- `GET /runs/{run_id}`

The UI separates project setup from task execution. Project setup stores the
project name, multiple public GitHub repository URLs, default branches, optional
path filters, and editable documentation context in the database. A run reuses
the saved project configuration and supports two modes: a period filter on each
repository default branch, or explicit branch selection per repository.

## Build A Project Knowledge Base

The knowledge index is built from the saved project settings: repository URLs,
default branches, path filters, and editable product context. In the browser UI,
open a saved project, go to **Run analysis**, and use **Build knowledge base**.

The same project-scoped operation is available through the API:

```bash
curl -X POST http://127.0.0.1:8770/projects/<project_id>/knowledge/index-runs \
  -H "Content-Type: application/json" \
  -d '{"max_files": 500}'
```

The resulting graph can be queried with:

```bash
curl -X POST http://127.0.0.1:8770/knowledge/context-pack \
  -H "Content-Type: application/json" \
  -d '{"project_id": "<project_id>", "goal": "Find terminal workflow context"}'
```

## Run One Fixture From CLI

```bash
uv run guidesync-agent-run fixtures/domain-guide-task.json
```

## Run Benchmarks

```bash
uv run guidesync-agent-benchmark fixtures/benchmark-suite.json
```

The default fixture uses the deterministic `mock` provider so the pipeline can be tested without API keys. Hosted and local models can be added through provider config.

For the preliminary report, run a separate comparison benchmark between the
local Gemma setup and a hosted flagship API model. The local setup validates
whether the prototype can run cheaply without external model calls; the hosted
setup is the intended deployment mode because it avoids running GPU model
servers for a public demo.

## Agent Provider Config

The browser UI does not display or accept model provider settings. Runtime
provider config comes from environment variables so local, benchmark, and
deployed runs are traceable and repeatable. The local development default is the
Gemma HTTP endpoint:

```bash
export GUIDESYNC_AGENT_PROVIDER=local_http
export GUIDESYNC_AGENT_MODEL=google/gemma-4-31b-qat
export GUIDESYNC_AGENT_BASE_URL=http://localhost:1234/api/v1/chat
export GUIDESYNC_AGENT_TIMEOUT_SECONDS=300
```

For deployed demos, prefer a hosted API provider instead of running local model
servers:

```bash
export GUIDESYNC_AGENT_PROVIDER=pydantic_ai
export GUIDESYNC_AGENT_MODEL=openai:gpt-4.1-mini
export GUIDESYNC_AGENT_API_KEY_ENV=OPENAI_API_KEY
export OPENAI_API_KEY=...
```

Direct API and benchmark fixtures can still include provider config for test
cases, but saved project runs prefer the environment configuration.

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

Example local HTTP provider for the prototype chat endpoint:

```json
{
  "provider": "local_http",
  "model": "google/gemma-4-31b-qat",
  "base_url": "http://localhost:1234/api/v1/chat",
  "timeout_seconds": 180
}
```

This provider expects responses shaped like `{"output": [{"type": "message", "content": "..."}]}` and parses the message content as a `DocumentationUpdate` JSON object.

## Report Artifact Storage

Local Docker Compose uses MinIO as S3-compatible storage:

```bash
GUIDESYNC_ARTIFACT_STORAGE=s3
GUIDESYNC_S3_BUCKET=guidesync-reports
GUIDESYNC_S3_ENDPOINT_URL=http://minio:9000
GUIDESYNC_S3_PREFIX=reports
AWS_ACCESS_KEY_ID=guidesync
AWS_SECRET_ACCESS_KEY=guidesync-secret
```

When `GUIDESYNC_ARTIFACT_STORAGE=s3`, generated artifacts are written under
`reports/{run_id}/` and the API returns `s3://bucket/key` artifact references.
Set `GUIDESYNC_S3_PUBLIC_BASE_URL` only if a controlled public/download layer is
available.

## Auth

Local development defaults to no authentication:

```bash
GUIDESYNC_AUTH_MODE=none
```

For a deployed demo, enable minimal Basic Auth:

```bash
GUIDESYNC_AUTH_MODE=basic
GUIDESYNC_AUTH_USERNAME=guidesync
GUIDESYNC_AUTH_PASSWORD=...
```

`GET /health` remains unauthenticated for service health checks. All UI and API
routes require credentials when Basic Auth is enabled.

## Postgres Storage

For a manually started Postgres instance:

```bash
export GUIDESYNC_DATABASE_URL=postgresql+psycopg://guidesync:guidesync@127.0.0.1:5432/guidesync
uv run guidesync-agent-api --host 127.0.0.1 --port 8770
```

Use Alembic for schema changes. The application still has a small `create_all`
fallback for test and prototype convenience, but Docker Compose applies
migrations before the API starts.

## Migrations

Alembic is configured in `alembic.ini` and `migrations/`. Docker Compose runs
`uv run alembic upgrade head` before starting the API.

Manual migration command:

```bash
export GUIDESYNC_DATABASE_URL=postgresql+psycopg://guidesync:guidesync@127.0.0.1:5432/guidesync
uv run alembic upgrade head
```

## AWS Deployment Baseline

`infra/cloudformation.yaml` describes a future economical deployment target:

- App Runner for the FastAPI container and public HTTPS URL;
- private RDS PostgreSQL for project/run metadata;
- private S3 bucket for reports;
- Secrets Manager for database password, Basic Auth credentials, and LLM API key.

The stack is not deployed by this repository. It is intended to support the
final report and a later public demo link after the image is pushed to ECR.
