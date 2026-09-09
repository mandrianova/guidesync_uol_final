# GuideSync Agent application

The final application prepares evidence-based release communication.
See [architecture](../docs/architecture.md), [evaluation](../docs/survey-results.md)
and the [final report](../docs/report/index.html). The [first prototype](../guidesync-mvp/README.md)
is retained as an archive.

## Local setup

Requirements: Docker with Compose, Git, and a separately configured inference
provider. Default local settings expect a compatible host model server on port
1234 with Gemma and Nomic available. Compose does not download LLM weights or
start a model server.

From this repository's root:

```bash
cd guidesync-agent
docker compose up --build
```

Open http://127.0.0.1:5173; API documentation is at http://127.0.0.1:8770/docs.
The frontend proxies API requests to the Compose `app` service. API, worker,
migrations, PostgreSQL, MinIO and LocalStack SQS run together. Do not start
additional host API, worker or Vite processes.

Ports overlap other GuideSync checkouts. Stop an existing stack yourself or
choose different host ports before starting this checkout. Development credentials
and disabled authentication make this a local setup, not a public deployment.

## First report

1. Configure saved model profiles and their role assignments in the UI.
2. Save a project, audience and accessible repository URL.
3. Sync the repository, build its profile and index documentation.
4. Select a repository change range and run analysis.
5. Review findings, warnings and the completed public report.
6. Print the report to PDF or generate its optional video and transcript.

A clean checkout does not contain historical report runs or private Ardor and
Functions repositories. Use your own authorised repository or a public example.
Model calls can consume provider quota or substantial local compute.

## Configuration

Defaults live in `docker-compose.yml`. Container-to-host inference URLs use
`host.docker.internal`, not `localhost`. The primary local model is
`google/gemma-4-31b-qat`, with `text-embedding-nomic-embed-text-v1.5` for retrieval.
Saved role profiles can select alternative models. Never commit credentials.

For optional Google credentials, use the explicit override and set
`GOOGLE_CLOUD_PROJECT`:

```bash
gcloud auth application-default login
docker compose -f docker-compose.yml -f docker-compose.google.yml up --build
```

Configure the intended Google profiles separately. The normal local Gemma path
requires no Google credential file. Make targets that manage Google models check
for host Google credentials; use the Compose commands above for the local path.

## Optional video

```bash
docker compose --profile video run --rm tts-model-download
docker compose run --rm app uv run --no-dev guidesync-agent-video-smoke \
  --output-dir /app/logs/video-smoke
```

Kokoro files are downloaded separately. The smoke exercises real speech and media
tooling. Video generation uses the persisted publication report without repeating
change analysis. Generated artifacts are stored in MinIO.

## Development checks

Run from `guidesync-agent/`:

```bash
docker compose config --quiet
docker compose run --rm app uv run ruff check .
docker compose run --rm app uv run ty check
docker compose run --rm app uv run pytest -m "not llm"
docker compose run --rm frontend sh -c "npm install && npm test && npm run build"
```

The current test fixture still uses temporary SQLite databases. This is a known
test-parity gap; these tests do not establish PostgreSQL runtime behaviour.
Runtime state uses PostgreSQL. Recorded test counts in the report refer to its
specific checkpoint, not every subsequent checkout.

After API/schema changes, regenerate the frontend contract through Compose:

```bash
docker compose run --rm frontend sh -c "npm install && npm run generate:api"
```

Do not hand-edit `frontend/src/api/generated/schema.ts`.

## Storage and operations

PostgreSQL holds project, knowledge, workflow and publication state. MinIO holds
artifacts. Repository clones and TTS models use dedicated named volumes. `logs/`
is ignored. `docker compose down` stops the stack; adding `--volumes` deletes
persistent local data and is not a normal restart command.

Report retries preserve the original run. Obsolete-run cleanup is a separate
explicit maintenance operation in `scripts/run_cleanup/`, not normal generation.
