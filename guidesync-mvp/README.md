# GuideSync MVP

GuideSync is a prototype documentation-maintenance agent for web products.

It reads repository changes over a configured period, identifies likely user-facing features, opens the configured UI with Playwright, detects the UI language, captures evidence screenshots and writes release-note style guide material for ordinary users.

## Generic Workflow

```text
project/task JSON
  -> collect git changes from configured repositories
  -> rank likely user-facing changes
  -> detect or apply the guide language
  -> generate release-mailing style notes
  -> capture configured feature routes in Playwright
  -> capture known route-less UI interactions when routes are unavailable
  -> rank features for the announcement from user impact and UI evidence
  -> review generated copy for user-facing quality
  -> produce HTML release notes with screenshots
  -> write agent report with actions and problems
```

## Project Layout

```text
project/guidesync-mvp/
├── agent/          # Agent skills and orchestration notes
├── db/             # deferred persistence notes
├── scripts/        # reusable CLI helpers
├── inputs/         # schemas and project/task input files
├── outputs/        # generated project/task artifacts
├── docs-fixtures/  # optional test fixtures
├── screenshots/    # legacy screenshot location; new runs write under outputs/
└── src/            # Python runtime
```

## Initialize A Project

```bash
cd project/guidesync-mvp
./scripts/init_project.sh my-product "My Product" /absolute/product/root
```

This creates:

```text
inputs/projects/my-product/project.json
inputs/projects/my-product/release-task.json
inputs/projects/my-product/.env.example
outputs/projects/my-product/tasks/
```

Copy `.env.example` to `.env` inside the project input directory and add project-specific tokens there.

## Run The Agent

```bash
cd project/guidesync-mvp
./scripts/run_release_agent.sh --input inputs/projects/my-product/release-task.json
```

If `output.dir` is omitted, artifacts are written to:

```text
outputs/projects/<project-id>/tasks/<task-id>/
```

## Input Shape

The recommended input is `inputs/release-task.schema.json`.

Key sections:

- `project`: product id, name, description, root and project-specific env file.
- `task`: task id, target audience and purpose.
- `task.language` / `task.locale`: optional guide language override.
- `task.languages` / `task.locales`: optional list when the UI is shipped in multiple languages.
- `task.example_context`: optional product/domain context for generated usage examples.
- `repositories`: git repositories to inspect.
- `period`: git-compatible time window.
- `auth`: auth mode and env variable names only.
- `ui`: URL, optional language/locale hints, launch mode, route overrides and screenshot settings.
- `output`: optional title, language/locale override and explicit output directory.

Guide language priority:

1. explicit lists such as `output.languages`, `task.languages`, or `ui.locales`;
2. `output.language` or `output.locale`;
3. `task.language` or `task.locale`;
4. `ui.language` or `ui.locale`;
5. captured UI evidence such as `<html lang>`, `navigator.language`, and visible UI labels;
6. English fallback.

When multiple languages are configured, the first language is written to `release-notes.html`; additional languages are written to `release-notes.<lang>.html`.

Each generated feature includes:

- why the change is useful;
- how to find and use it;
- practical usage examples for the configured audience;
- optional screenshots. Technical evidence stays in JSON so the HTML reads like a user-facing release mailing.

Every run also writes `agent-report.md` with:

- what the agent did;
- which artifacts were produced;
- selected user-facing updates;
- browser capture status;
- announcement priority rationale;
- copy review warnings and runtime problems.

Screenshot planning is not limited to newly added routes. If a selected change has a UI surface but no route, the release agent should use interaction recipes where possible, such as opening the chat composer and typing `/` for slash commands or `@` for resource mentions.

Screenshots are QA-checked before they are used in the HTML. The capture step rejects known bad states such as 404 pages, can retry alternate routes or waits, and crops/highlights screenshots so the final announcement shows the relevant UI instead of a full raw browser page.

## Docker UI Launch

To avoid port conflicts, configure the UI in task JSON.

Docker Compose:

```json
{
  "ui": {
    "url": "http://localhost:3100",
    "launch": {
      "mode": "docker_compose",
      "compose_file": "/path/to/docker-compose.yml",
      "project_name": "guidesync-ui",
      "service": "frontend",
      "wait_url": "http://localhost:3100",
      "timeout_seconds": 120,
      "down_after": true
    }
  }
}
```

Docker image:

```json
{
  "ui": {
    "url": "http://localhost:3100",
    "launch": {
      "mode": "docker_run",
      "image": "frontend:local",
      "name": "guidesync-ui",
      "ports": ["3100:3000"],
      "env_file": "inputs/projects/my-product/.env",
      "wait_url": "http://localhost:3100",
      "down_after": true
    }
  }
}
```

## Runtime

```bash
uv sync
uv run playwright install chromium
```

Primary entrypoint:

```bash
./scripts/run_release_agent.sh --input <release-task.json>
```

The browser plugin is a diagnostic fallback only. The repeatable path is Python Playwright.
