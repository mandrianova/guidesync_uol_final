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
- Use absolute repository paths in task JSON unless the paths are relative to `project.root`.
- Keep one project id per product or deployment target.
