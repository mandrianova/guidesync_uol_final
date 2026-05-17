# Environment Setup Skill

Use this skill before launching the UI or capturing screenshots.

## Purpose

Check whether the local environment has enough tooling and configuration for the GuideSync MVP run.

## Required Checks

- Git is available.
- Node or the product-specific frontend runtime is available if the UI is launched locally.
- Node is available for helper scripts.
- Repositories listed in the incoming task exist.
- The configured UI launch mode is available, for example Docker for `docker_run` or `docker_compose`.
- Project-specific `.env` and `.env.example` exist where expected.
- Auth mode is known from the incoming task.

## Helper Script

From the CM3070 project root:

```bash
project/guidesync-mvp/scripts/environment_check.sh
```

## Rules

- Do not overwrite `.env`.
- Do not print secret values.
- Do not start backend services until the required workflow is selected.
- Prefer recording blockers under `project/guidesync-mvp/analysis/`.
