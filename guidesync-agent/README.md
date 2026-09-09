# GuideSync Agent application

The final application prepares evidence-based release communication.
See [architecture](../docs/architecture.md), [evaluation](../docs/survey-results.md)
and the [final report](../docs/report/index.html). The [first prototype](../guidesync-mvp/README.md)
is retained as an archive.

## Local setup

Requirements: Docker with Compose, Git, and a separately configured inference
provider. The local configuration used for this project runs Gemma and Nomic
through LM Studio on the host, on port 1234. Compose does not install LM Studio,
download these model weights or start the model server.

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

### Local model dependencies

The local baseline uses the following models, as recorded in the final report
and application configuration:

| Model | Runtime | Role |
| --- | --- | --- |
| `google/gemma-4-31b-qat` | LM Studio on the host | Local LLM/VLM for project profiling, code-change analysis, report generation and screenshot review |
| `text-embedding-nomic-embed-text-v1.5` | LM Studio on the host | Text embeddings for semantic retrieval and ranking of relevant documentation |
| spaCy `en_core_web_sm` 3.8.0 | Python inside the Compose containers | Basic linguistic annotation of documentation; installed with the application dependencies |

Before generating a report:

1. Install LM Studio and download the Gemma and Nomic models listed above.
2. Load both models and enable the OpenAI-compatible local server on port 1234.
   Use the model identifiers above, or update GuideSync's configuration to match
   the identifiers exposed by your server.
3. In GuideSync, configure the saved local model profiles and role assignments
   with base URL `http://host.docker.internal:1234/v1` and the Gemma model ID.
   The embedding endpoint and Nomic model ID are already the Compose defaults.

With the LM Studio CLI (`lms`) installed and the Nomic model downloaded,
`make lmstudio-embedding` starts the server, loads Nomic if necessary with a
2,048-token context, and checks the embedding endpoint. Load Gemma separately;
this helper only prepares embeddings.

Gemma and Nomic need sufficient host memory to stay loaded together. Available
memory, model quantization and context length determine local hardware needs;
the repository does not establish a tested minimum RAM requirement. spaCy runs
independently of LM Studio. Optional Kokoro speech synthesis also runs separately
inside the application; see [Optional video](#optional-video).

### Provider configuration

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
