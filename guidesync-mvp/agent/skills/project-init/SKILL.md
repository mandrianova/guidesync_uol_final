# Project Init Skill

Use this skill when setting up GuideSync for a new product or documentation target.

## Purpose

Create an isolated project configuration so runs for different products do not share auth files, outputs or task defaults.

## Output Layout

Project configuration lives under:

```text
inputs/projects/<project-id>/
```

Generated run artifacts live under:

```text
outputs/projects/<project-id>/tasks/<task-id>/
```

## Command

Preferred JSON-driven initialization:

```bash
project/guidesync-mvp/scripts/run_task.sh project/guidesync-mvp/inputs/projects/<project-id>/init-project-task.json
```

The dispatcher calls `scripts/init_project_from_task.sh`, scans `ui.repository` / `ui.repositories` when provided, writes project config under `inputs/projects/<project-id>/`, and writes the init report under `outputs/projects/<project-id>/init-report.json`.

After the command finishes, immediately run the project validation workflow from `agent/skills/project-validation/SKILL.md`. The script only generates first-pass artifacts; the agent decides whether the logo, colors, repositories, languages and release task are correct.

Legacy shorthand:

```bash
project/guidesync-mvp/scripts/init_project.sh <project-id> "<Project Name>" <project-root>
```

The command creates:

- `project.json`
- `release-task.json`
- `.env.example`

Copy `.env.example` to `.env` inside the project input directory and put project-specific tokens there. Do not use one global `.env` for all products.

## Rules

- Keep secrets out of task JSON.
- Store only env variable names in task JSON, for example `GUIDESYNC_AUTH0_TOKEN`.
- For UI branding/theme discovery, prefer `ui.repository` or `ui.repositories` over `ui.url`. A deployed URL may be sparse or unauthenticated; the repository is the source of truth for logo, colors and UI conventions.
- Use absolute repository paths in task JSON unless the paths are relative to the init task file or `project.root`.
- Keep one project id per product or deployment target.
