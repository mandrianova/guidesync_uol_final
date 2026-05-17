# Task Input Skill

Use this skill when the GuideSync agent receives or prepares an incoming documentation-maintenance task.

## Purpose

Convert a vague request such as "check recent changes and update the guide" into a structured task with:

- project id, name and base description;
- time window;
- scoped repositories;
- branch/ref targets;
- UI URL and launch command;
- auth mode;
- workflow goal;
- documentation target;
- output locations.

## Files

- Release task schema: `project/guidesync-mvp/inputs/release-task.schema.json`
- Project init task schema: `project/guidesync-mvp/inputs/project-init-task.schema.json`
- Project schema: `project/guidesync-mvp/inputs/project.schema.json`
- Project examples: `project/guidesync-mvp/inputs/projects/<project-id>/`

## Execution Contract

Start by understanding the task, then use the dispatcher as the safe tool for deterministic execution:

From the CM3070 project root:

```bash
project/guidesync-mvp/scripts/run_task.sh <task-json>
```

Do not manually create run directories or call lower-level scripts for normal task execution. The dispatcher detects:

- `task.type == "project_init"` -> project initialization;
- `period` + `repositories` release task -> release-notes agent;

After any script run, inspect the generated artifacts and decide whether the task is actually complete. A zero exit code only means the tool ran; the agent is responsible for validation, follow-up fixes and final acceptance.

If a task points to `release-task.schema.json` or has `period` and `repositories`, do not create run directories manually. Use `run_task.sh` as the tool; then review `release-notes.html`, `release-notes.json`, screenshots and `agent-report.md`.

## Rules

- Do not include secrets in the task JSON.
- Use the configured ref for diff discovery; default to `HEAD` unless the task explicitly requests another ref.
- Record auth as a mode and notes, not raw credentials.
- Store project-specific tokens in the project input directory, not in one global `.env`.
- Keep output paths under `outputs/projects/<project-id>/tasks/<task-id>/` unless the task explicitly requests another output directory.
