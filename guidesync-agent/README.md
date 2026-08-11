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

Architecture, runtime rules, and code-style guidance for future changes live in:

- [`docs/project-rules-and-structure.md`](docs/project-rules-and-structure.md)
- [`docs/code-style-guide.md`](docs/code-style-guide.md)

## Local Setup

The canonical local development path is Docker Compose. The Compose file is
local-only: it starts the React frontend, FastAPI backend, worker, Postgres,
MinIO, and LocalStack SQS with dev-friendly mounts:

```bash
cd project/guidesync-agent
docker compose up --build
```

Open:

- React frontend: `http://127.0.0.1:5173`
- FastAPI API/docs: `http://127.0.0.1:8770/docs`
- MinIO console: `http://127.0.0.1:9001`
- LocalStack SQS: `http://127.0.0.1:4566`

Inside Compose, the API container runs `uvicorn --reload`, `src/` is mounted
into the API and worker containers, and Vite proxies API calls to the `app`
service. CORS is enabled for `127.0.0.1:5173` and `localhost:5173`.

Do not start the application through host `uvicorn`, host worker processes, or
host Vite for implementation or browser QA. Use direct host process commands
only for narrow static maintenance checks, and do not report them as application
runtime validation. Browser or `curl` checks should target the Compose service
ports.

The runtime data path is Postgres for project/run/profile/workflow/knowledge
metadata and S3-compatible storage for generated report artifacts. File/JSON
stores are not supported; tests that need isolated storage create temporary
SQLite databases with the same SQLAlchemy schema.

## Docker Compose Services

`docker compose up --build` starts:

- `db`: Postgres with the `guidesync` database;
- `minio`: local S3-compatible storage on `http://127.0.0.1:9000`;
- `bucket-init`: creates the `guidesync-reports` bucket;
- `sqs`: LocalStack SQS for repository clone/fetch tasks;
- `sqs-init`: creates the `guidesync-repository-sync` queue;
- `app`: FastAPI on `http://127.0.0.1:8770`;
- `worker`: background process that handles repository sync SQS messages and claims queued
  report runs from Postgres;
- `frontend`: Vite React app on `http://127.0.0.1:5173`.

Published ports are bound to `127.0.0.1` for local development. The database and
MinIO are also available to the application through the internal Compose network
at `db:5432`, `minio:9000`, and `sqs:4566`.

## Run API And Worker

Run the API and worker through Docker Compose:

```bash
cd project/guidesync-agent
docker compose up --build app worker frontend
```

Project report creation is asynchronous. `POST /projects/{project_id}/runs`
saves a queued workflow/run record and returns immediately. The worker claims
eligible project workflow tasks, updates status to `running`, executes the
pipeline, and then persists `completed` or `failed`.

Repository cache synchronization is asynchronous through LocalStack SQS in the
Compose runtime. Project create/update and
`POST /projects/{project_id}/repositories/{repository_id}/sync` enqueue
clone/fetch work and mark the repository `syncing`; the worker processes that
queue and persists `ready` or `failed` cache metadata. Avoid direct local
clone/fetch fallbacks for runtime validation.

Useful endpoints:

- `GET /` browser UI for launching runs and reviewing results
- `GET /health`
- `GET /projects`
- `POST /projects`
- `PUT /projects/{project_id}`
- `POST /projects/{project_id}/runs`
- `GET /projects/{project_id}/runs`
- `POST /projects/{project_id}/repositories/{repository_id}/sync`
- `GET /projects/{project_id}/repositories/{repository_id}/status`
- `GET /projects/{project_id}/repositories/{repository_id}/branches`
- `POST /projects/{project_id}/knowledge/index-runs`
- `GET /projects/{project_id}/knowledge/index-runs`
- `POST /knowledge/search`
- `POST /knowledge/context-pack`
- `GET /github/branches?url=...` compatibility alias backed by the local repository cache
- `POST /runs`
- `GET /runs`
- `GET /runs/{run_id}`

## Run React Frontend

The React frontend lives in `frontend/` and is run by Docker Compose for local
application development.

```bash
cd project/guidesync-agent
docker compose up --build frontend
```

Open `http://127.0.0.1:5173`. Use Compose-backed `npm run build` for a
TypeScript and production-bundle check:

```bash
cd project/guidesync-agent
docker compose run --rm frontend sh -c "npm install && npm run build"
```

The frontend API client is generated from the FastAPI OpenAPI schema. When
backend routes or schemas change, run the Compose API and refresh the generated
SDK through the frontend service:

```bash
cd project/guidesync-agent
docker compose run --rm frontend sh -c "npm install && npm run generate:api"
```

The generation script reads `GUIDESYNC_OPENAPI_URL`. Docker Compose sets it to
`http://app:8770/openapi.json`, while the package script keeps
`http://127.0.0.1:8770/openapi.json` only as a host fallback for narrow static
maintenance.

For production builds that call a deployed API domain, pass the environment
through the Compose frontend service:

```bash
cd project/guidesync-agent
docker compose run --rm \
  -e VITE_GUIDESYNC_API_BASE_URL=https://api.guidesync.devlogirl.com \
  frontend sh -c "npm install && npm run build"
```

The UI separates project setup from task execution. Project setup stores the
project name, multiple public GitHub repository URLs, default branches, optional
path filters, and editable documentation context in the database. A run reuses
the saved project configuration and supports two modes: a period filter on each
repository default branch, or explicit branch selection per repository.

## Build A Project Knowledge Base

The knowledge index is built from the saved project settings: repository URLs,
default branches, path filters, and editable product context. In the browser UI,
open a saved project, go to **Run analysis**, and use **Build knowledge base**.
The index also runs the annotation NLP layer described in
[`docs/annotation-nlp-pipeline.md`](docs/annotation-nlp-pipeline.md), using the
latest project-profile taxonomy when one is available.

The same project-scoped operation is available through the API:

```bash
curl -X POST http://127.0.0.1:8770/projects/<project_id>/knowledge/index-runs
```

The resulting graph can be queried with:

```bash
curl -X POST http://127.0.0.1:8770/knowledge/context-pack \
  -H "Content-Type: application/json" \
  -d '{"project_id": "<project_id>", "goal": "Find terminal workflow context"}'
```

## Run One Fixture From CLI

```bash
cd project/guidesync-agent
docker compose run --rm app uv run guidesync-agent-run fixtures/domain-guide-task.json
```

## Run Benchmarks

```bash
cd project/guidesync-agent
docker compose run --rm app uv run guidesync-agent-benchmark fixtures/benchmark-suite.json
```

The default fixture uses the deterministic `mock` provider so the pipeline can be tested without API keys. Hosted and local models can be added through provider config.

For end-to-end validation against an upstream repository, follow
[`docs/real-project-validation-protocol.md`](docs/real-project-validation-protocol.md).
The generation goal must remain generic and must not disclose the change,
expected screenshots, or evaluator-only gold facts.

For the preliminary report, run a separate comparison benchmark between the
local Gemma setup and a hosted flagship API model. The local setup validates
whether the prototype can run cheaply without external model calls; the hosted
setup is the intended deployment mode because it avoids running GPU model
servers for a public demo.

## Agent Provider Config

The browser UI includes a model settings page for saved model profiles. Runtime
defaults still come from environment variables so local, benchmark, and deployed
runs are traceable and repeatable. In local development, set these values
through the Compose service environment or `.env` used by Compose. The local
Compose default is an OpenAI-compatible Gemma endpoint reachable from containers
through `host.docker.internal`:

```bash
GUIDESYNC_AGENT_PROVIDER=pydantic_ai
GUIDESYNC_MODEL_BUNDLE=local_open_source
GUIDESYNC_MODEL_PROVIDER_FAMILY=open_source
GUIDESYNC_AGENT_MODEL=openai:google/gemma-4-31b-qat
GUIDESYNC_AGENT_BASE_URL=http://host.docker.internal:1234/v1
GUIDESYNC_AGENT_API_KEY_ENV=
GUIDESYNC_AGENT_TIMEOUT_SECONDS=600
GUIDESYNC_AGENT_THINKING=high

GUIDESYNC_LLM_BASE_URL=http://host.docker.internal:1234/v1
GUIDESYNC_PROJECT_PROFILE_AGENT_PROVIDER=pydantic_ai
GUIDESYNC_PROJECT_PROFILE_AGENT_BASE_URL=http://host.docker.internal:1234/v1
GUIDESYNC_PROJECT_PROFILE_AGENT_MODEL=openai:google/gemma-4-31b-qat
GUIDESYNC_PROJECT_PROFILE_AGENT_API_KEY_ENV=
GUIDESYNC_PROJECT_PROFILE_AGENT_TIMEOUT_SECONDS=600
GUIDESYNC_CODE_CHANGE_ANALYSIS_PROVIDER=pydantic_ai
GUIDESYNC_CODE_CHANGE_ANALYSIS_BASE_URL=http://host.docker.internal:1234/v1
GUIDESYNC_CODE_CHANGE_ANALYSIS_MODEL=openai:google/gemma-4-31b-qat
GUIDESYNC_CODE_CHANGE_ANALYSIS_API_KEY_ENV=
GUIDESYNC_CODE_CHANGE_ANALYSIS_TIMEOUT_SECONDS=600
GUIDESYNC_SCREENSHOT_VISION_PROVIDER=local_http
GUIDESYNC_SCREENSHOT_VISION_BASE_URL=http://host.docker.internal:1234/v1
GUIDESYNC_SCREENSHOT_VISION_MODEL=openai:google/gemma-4-31b-qat
GUIDESYNC_SCREENSHOT_VISION_API_KEY_ENV=
GUIDESYNC_SCREENSHOT_VISION_TIMEOUT_SECONDS=600
GUIDESYNC_SEMANTIC_RANKER_MODE=embedding_endpoint
GUIDESYNC_EMBEDDING_BASE_URL=http://host.docker.internal:1234/v1
GUIDESYNC_EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
```

The role-specific model-selection rationale is documented in
`docs/model-selection-appendix.md`. `GUIDESYNC_AGENT_*` is the orchestrator /
final documentation role, while project profiling, code-change analysis, and
screenshot vision use their own role-specific settings and persist role/model
metadata in generated artifacts.

To opt into the Google bundle without changing the local fallback defaults,
authenticate on the host and seed saved role profiles into Postgres:

```bash
gcloud auth application-default login
gcloud config set project <project-id>
make seed-google-models
make restart
```

`make seed-google-models` runs through the normal Compose stack, mounts the host
ADC JSON into the app container, and creates or updates Google Gemini profiles
assigned to `orchestrator`, `project_profile_file_reader`,
`code_change_analysis`, and `screenshot_vision`. The resolver uses these saved
role assignments first. Roles without a saved assignment continue to use the
local environment/default model. The Compose default for
`GOOGLE_CLOUD_LOCATION` is `global`; override it only after confirming the
selected Gemini models are available in the target region. Use the normal
`make restart` or `make up` after seeding so `app`, `worker`, and `migrate` all
receive the mounted ADC file and Google Cloud env vars.

For deployed demos, prefer a hosted API provider instead of running local model
servers:

```bash
GUIDESYNC_AGENT_PROVIDER=pydantic_ai
GUIDESYNC_AGENT_MODEL=openai:gpt-4.1-mini
GUIDESYNC_AGENT_API_KEY_ENV=OPENAI_API_KEY
OPENAI_API_KEY=...
```

`GUIDESYNC_AGENT_THINKING` is optional. Supported values are `true`, `false`,
`minimal`, `low`, `medium`, `high` and `xhigh`; omit it for provider defaults.
Pydantic AI maps this setting to the provider when the selected model supports
reasoning or thinking. Local OpenAI-compatible servers may ignore it unless the
server and model expose a compatible reasoning mode.

Direct API and benchmark fixtures can still include provider config for test
cases, but saved project runs prefer the environment configuration.

Example hosted provider:

```json
{
  "provider": "pydantic_ai",
  "model": "openai:gpt-5.2",
  "api_key_env": "OPENAI_API_KEY",
  "thinking": "high"
}
```

Example local provider using an OpenAI-compatible local endpoint:

```json
{
  "provider": "pydantic_ai",
  "model": "openai:local-model",
  "base_url": "http://host.docker.internal:11434/v1",
  "api_key_env": "LOCAL_MODEL_API_KEY"
}
```

The exact local endpoint depends on the backend, for example Ollama, llama.cpp server, vLLM, or another OpenAI-compatible server.

Example local HTTP provider for the prototype chat endpoint:

```json
{
  "provider": "local_http",
  "model": "google/gemma-4-31b-qat",
  "base_url": "http://host.docker.internal:1234/v1",
  "timeout_seconds": 180,
  "thinking": "high"
}
```

This provider expects responses shaped like `{"output": [{"type": "message", "content": "..."}]}` and parses the message content as a `DocumentationUpdate` JSON object.

## Report Artifact Storage

Local Docker Compose uses MinIO as S3-compatible storage:

```bash
GUIDESYNC_S3_BUCKET=guidesync-reports
GUIDESYNC_S3_ENDPOINT_URL=http://minio:9000
GUIDESYNC_S3_PREFIX=reports
AWS_ACCESS_KEY_ID=guidesync
AWS_SECRET_ACCESS_KEY=guidesync-secret
```

Generated artifacts are written under `reports/{run_id}/` and the API returns
`s3://bucket/key` artifact references.
Set `GUIDESYNC_S3_PUBLIC_BASE_URL` only if a controlled public/download layer is
available.

## Optional video presentation

Runs may request a `disabled`, `optional`, or `required` final video stage after
the persisted public report is ready. Install the pinned local Kokoro model once
and run the deterministic real-media smoke through Compose:

```bash
docker compose --profile video run --rm tts-model-download
docker compose run --rm app uv run --no-dev guidesync-agent-video-smoke \
  --output-dir /app/logs/video-smoke
```

The smoke does not call an LLM. It renders controlled 1280x720 slides, generates
real English narration, assembles H.264/AAC MP4, and applies the same `ffprobe`
gates as the worker.

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

Local runtime storage is provided by the Compose `db` service. Do not start the
API against a manually configured host Postgres instance for browser QA or
runtime validation.

To run a database-backed CLI command, use the Compose `app` service so it sees
the same `GUIDESYNC_DATABASE_URL` as the API and worker:

```bash
cd project/guidesync-agent
docker compose run --rm app uv run guidesync-agent-run fixtures/domain-guide-task.json
```

Use Alembic for schema changes. Docker Compose applies migrations before the API
and worker start.

## Migrations

Alembic is configured in `alembic.ini` and `migrations/`. Docker Compose runs
`uv run alembic upgrade head` before starting the API.

Manual migration command through Compose:

```bash
cd project/guidesync-agent
docker compose run --rm migrate
```

## AWS Deployment Baseline

`infra/cloudformation.yaml` describes a future economical deployment target:

- App Runner for the FastAPI container and public HTTPS URL;
- private RDS PostgreSQL for project/run metadata;
- private S3 bucket for reports;
- Secrets Manager for database password, Basic Auth credentials, and LLM API key.

The stack is not deployed by this repository. It is intended to support the
final report and a later public demo link after the image is pushed to ECR.
