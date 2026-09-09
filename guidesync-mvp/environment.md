# GuideSync MVP Environment

This document defines the generic runtime contract for GuideSync.

## Required Local Inputs

- GuideSync workspace:
  - `project/guidesync-mvp`
- Project input directory:
  - `guidesync-mvp/inputs/projects/<project-id>/`
- Release task JSON:
  - `guidesync-mvp/inputs/projects/<project-id>/release-task.json`
- Project-specific `.env`:
  - referenced by `project.env_file` or `auth.env_file` in the task input.

## Required Runtime Tools

Minimum:

- Git
- Python 3.11+
- `uv`
- Playwright Python runtime
- Node, for helper scripts

Optional depending on the configured product:

- Docker, for `ui.launch.mode = docker_run` or `docker_compose`
- Bun/npm/pnpm/yarn, if launching a frontend directly
- Product-specific backend services

## Auth Strategy

Supported options:

1. Project-specific token env file, for example `inputs/projects/<project-id>/.env`.
2. Pre-authenticated Playwright storage state with `auth.state_path`.
3. Manual login in headed Playwright for local debugging only.
4. No auth for public or fixture UIs.

Do not store raw tokens in task JSON. Store the environment variable name only.

## Output Layout

Default output location:

```text
outputs/projects/<project-id>/tasks/<task-id>/
```

Typical artifacts:

- `release-notes.html`
- `release-notes.json`
- `screenshot-plan.json`
- `browser-capture.json`
- `screenshots/*.png`
- `guide-update.md`

## Setup

```bash
cd guidesync-mvp
uv sync
uv run playwright install chromium
```

Initialize a new project:

```bash
guidesync-mvp/scripts/init_project.sh my-product "My Product" /absolute/product/root
```

Run an agent task:

```bash
guidesync-mvp/scripts/run_release_agent.sh \
  --input guidesync-mvp/inputs/projects/my-product/release-task.json
```

## Environment Risks

- Auth may depend on external identity provider configuration.
- Local branches may not match the deployed UI.
- Secrets or customer data must not be copied into MVP outputs.
- Screenshots should be masked or cropped before public documentation use.
