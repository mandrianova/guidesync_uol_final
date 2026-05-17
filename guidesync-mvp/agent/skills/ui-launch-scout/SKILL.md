# UI Launch Scout Skill

Use this skill when preparing to run a configured product UI for screenshot capture.

## Goal

Identify the minimum local setup needed to open the relevant UI workflow in a browser.

The UI target comes from the task input `ui` block. Supported launch modes include existing URL, Docker Compose, Docker run and arbitrary command launch.

## Rules

- Inspect environment files and README/setup docs before starting the dev server.
- Do not overwrite `.env` files or local configuration.
- If credentials/auth are needed, prefer a safe local test user, token or pre-authenticated browser state.
- Prefer a workflow that can be reached with minimal backend dependencies.
- Capture any setup blockers in `project/guidesync-mvp/analysis/`.

## Evidence To Collect

- command used to start UI;
- URL opened;
- auth method, if any;
- route/workflow selected;
- screenshots captured;
- UI text or accessibility context captured.
