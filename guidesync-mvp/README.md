# GuideSync MVP

> Archive status: this first prototype is retained for reference only. Active development has moved
> to `project/guidesync-agent/`.

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
inputs/projects/my-product/templates/brand.css
inputs/projects/my-product/assets/logo.svg
inputs/projects/my-product/.env.example
outputs/projects/my-product/tasks/
```

Copy `.env.example` to `.env` inside the project input directory and add project-specific tokens there.

Project initialization can also be driven by JSON so the agent can create the project theme from a task input:

```bash
cd project/guidesync-mvp
./scripts/run_task.sh inputs/projects/ardor/init-project-task.json
```

The init task writes project-local branding assets under `inputs/projects/<project-id>/templates/brand.css` and `inputs/projects/<project-id>/assets/logo.svg`. Release tasks reference those files through `project.branding`, so the shared Jinja release notes template can inherit project colors and logo without hard-coded product styling.

For initialization, prefer `ui.repository` or `ui.repositories` over `ui.url`. The init step inspects the UI repository files to discover logo, colors and copy defaults. `ui.url` is optional runtime context for later browser checks and can be empty when the deployed page does not expose enough UI.

Init run reports are generated under:

```text
outputs/projects/<project-id>/init-report.json
```

## Run The Agent

```bash
cd project/guidesync-mvp
./scripts/run_task.sh inputs/projects/my-product/release-task.json
```

If `output.dir` is omitted, artifacts are written to:

```text
outputs/projects/<project-id>/tasks/<task-id>/
```

## Local Task UI

Run the small local task console:

```bash
cd project/guidesync-mvp
./scripts/run_ui.sh --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`.

The UI can create `project_init` and `release` task JSON files under `inputs/projects/<project-id>/`, run them through `scripts/run_task.sh`, and show generated HTML, JSON, reports and screenshots from `outputs/projects/<project-id>/`.

## Input Shape

The recommended input is `inputs/release-task.schema.json`.

Key sections:

- `project`: product id, name, description, root and project-specific env file.
- `project.languages`: localized outputs to produce. `release-notes.html` is generated in English first; additional languages are written as `release-notes.<lang>.html`.
- `project.branding`: optional project-local logo and CSS files for the release notes template.
- `ui.repository` / `ui.repositories` in project init tasks: UI repository paths used to discover branding and interface conventions.
- `task`: task id, target audience and purpose.
- `task.language` / `task.locale`: optional guide language override.
- `task.languages` / `task.locales`: optional list when the UI is shipped in multiple languages.
- `task.example_context`: optional product/domain context for generated usage examples.
- `repositories`: git repositories to inspect.
- `period`: git-compatible time window.
- `auth`: auth mode and env variable names only.
- `ui`: URL, optional language/locale hints, launch mode, route overrides and screenshot settings.
- `output`: optional title, language/locale override and explicit output directory.

Language flow:

1. Generate the primary release announcement in English.
2. Use `project.languages`, `output.languages`, `task.languages`, or `ui.locales` to decide which localized files are needed.
3. Use captured UI evidence such as `<html lang>`, `navigator.language`, and visible UI labels as a signal when no explicit project languages are configured.
4. Write additional localized versions as `release-notes.<lang>.html`.

English is always the canonical `release-notes.html`; translation/localization is a separate final pipeline stage.

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

## Release Notes Template

The final HTML is rendered with Jinja from `src/guidesync_mvp/templates/release_notes.html`. Python prepares a view model with selected features, priority, labels, screenshots and project branding; the template owns the HTML structure and visual layout. Project CSS is loaded from `project.branding.css_file` and injected after the base CSS variables.

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
