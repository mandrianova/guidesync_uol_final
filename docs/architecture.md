# GuideSync architecture

GuideSync combines agent-led investigation with deterministic workflow control.
Agents use bounded tools and saved results from earlier stages. Application code
owns stage order, execution limits, retries, validation and artifact handling.

## Components

| Component | Responsibility |
| --- | --- |
| React, Mantine, Vite | Project setup, model settings, workflow inspection and report review |
| FastAPI, Pydantic | Typed API contracts and request validation |
| Worker | Durable workflows and queued repository synchronisation |
| PostgreSQL, SQLAlchemy | Projects, profiles, knowledge, findings, workflow state and publication snapshots |
| MinIO | S3-compatible storage for reports, screenshots and media |
| LocalStack SQS | Standalone repository synchronisation queue |
| Alembic | Database schema migrations |

Routes delegate to controllers, services/workflows and storage adapters. ORM
models remain persistence details. Pydantic schemas define the API and generated
TypeScript contract. Compose runs the complete local dependency graph.

## Evidence workflow

1. **Repository sync:** clone or update an authorised repository in the cache.
2. **Project profile:** an agent reads bounded evidence and saves product context
   and documentation categories.
3. **Knowledge index:** index documentation with linguistic annotations and a
   semantic retrieval signal.
4. **Change plan:** freeze the selected base-to-head path inventory. Commit history
   provides bounded optional context.
5. **Change analysis:** a resumable agent examines raw diffs, relevant files and
   knowledge. Findings and explicit inventory coverage are saved durably.
6. **Synthesis:** a fresh context reads the saved findings to write release
   communication. Incomplete coverage does not unlock synthesis.
7. **UI evidence:** a separate stage captures and reviews requested screenshots;
   failures remain visible as warnings.
8. **Publication:** a persisted `PublicationReport` supplies shared facts for the
   public report, PDF printing and optional video/transcript.

Saved intermediate results reduce dependence on a single long conversation.
Retry history remains inspectable. Humans decide whether to publish externally.

## Model roles

| Model | Type | Role |
| --- | --- | --- |
| Gemma 4 31B QAT | Local multimodal LLM | Code reasoning, writing and screenshot interpretation |
| GPT-5.6 Sol | Hosted LLM | Evaluated alternative for reasoning and synthesis |
| Nomic Embed Text v1.5 | Embedding model | Semantic retrieval signal |
| spaCy en_core_web_sm | NLP pipeline | Linguistic candidates for document annotation |
| Kokoro English v0.19 | Text-to-speech model | Speech from checked narration |

These are pre-trained components, not models trained by this project. Supporting
NLP and embedding operations can be invoked by application code; not every stage
is an autonomous agent or a direct LLM tool call. Saved role profiles support
model choice without rewriting the workflow.

## Source map

Under `guidesync-agent/src/guidesync_agent/`:

- `routes/`, `controllers/`: HTTP boundary and use cases.
- `services/`, `workflows/`: domain operations and durable execution.
- `agent_runtime/`, `tools/`, `prompts/`: model execution and bounded tools.
- `schemas/`, `models/`, `storage/`: contracts and persistence.

`guidesync-agent/frontend/src/api/generated/` contains generated client types;
`guidesync-agent/migrations/` contains schema revisions.

The completed MVP targets release communication. See the [report](report/index.html)
and [survey results](survey-results.md) for evidence and limitations.
