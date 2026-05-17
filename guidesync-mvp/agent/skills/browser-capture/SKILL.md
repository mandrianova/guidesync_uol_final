# Browser Capture Skill

Use this skill to execute a screenshot plan against the running UI.

## Purpose

Open the product UI in a browser, follow the screenshot plan, capture screenshots and collect UI evidence.

## Inputs

- `outputs/<run>/screenshot-plan.json`;
- incoming task JSON;
- running UI URL;
- auth mode;
- screenshot output directory.

## Outputs

- screenshots in `screenshots/<run>/`;
- `outputs/<run>/browser-capture.json` containing:
  - visited URLs;
  - screenshot paths;
  - visible text or accessibility snapshot summary;
  - failed steps;
  - manual intervention notes.

## Rules

- Do not capture secrets, tokens or private customer data.
- Pass auth tokens through environment variables only; never write them into screenshot plans, logs or generated documentation.
- If manual login is required, pause and record it as manual intervention.
- Prefer deterministic browser actions.
- Prefer `--storage-state` or token environment auth for repeatable local and CI runs.
- Keep the Codex/browser plugin only as a diagnostic fallback; the primary capture path is Python Playwright.
- If a step fails, capture a diagnostic screenshot and continue only if safe.

## Runtime

Use Python Playwright through the local `uv` environment.

Setup:

```bash
cd project/guidesync-mvp
uv sync
uv run playwright install chromium
```

Capture:

```bash
project/guidesync-mvp/scripts/capture_screenshots.sh \
  outputs/projects/<project-id>/tasks/<task-id>/screenshot-plan.json \
  outputs/projects/<project-id>/tasks/<task-id>/screenshots \
  outputs/projects/<project-id>/tasks/<task-id>/browser-capture.json \
  --headed \
  --manual-auth
```

Token-assisted local capture:

```bash
GUIDESYNC_AUTH0_TOKEN=<redacted> \
project/guidesync-mvp/scripts/capture_screenshots.sh \
  outputs/projects/<project-id>/tasks/<task-id>/screenshot-plan.json \
  outputs/projects/<project-id>/tasks/<task-id>/screenshots \
  outputs/projects/<project-id>/tasks/<task-id>/browser-capture.json \
  --auth0-token-env GUIDESYNC_AUTH0_TOKEN
```

Stored-state capture:

```bash
project/guidesync-mvp/scripts/capture_screenshots.sh \
  outputs/projects/<project-id>/tasks/<task-id>/screenshot-plan.json \
  outputs/projects/<project-id>/tasks/<task-id>/screenshots \
  outputs/projects/<project-id>/tasks/<task-id>/browser-capture.json \
  --storage-state .local/auth-state.json
```
