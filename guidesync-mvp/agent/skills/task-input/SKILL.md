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

- Schema: `project/guidesync-mvp/inputs/task.schema.json`
- Release task schema: `project/guidesync-mvp/inputs/release-task.schema.json`
- Project schema: `project/guidesync-mvp/inputs/project.schema.json`
- Example: `project/guidesync-mvp/inputs/example-release-task.json`

## Validation

From the CM3070 project root:

```bash
project/guidesync-mvp/scripts/validate_task_input.sh project/guidesync-mvp/inputs/example-task-domains.json
```

## Rules

- Do not include secrets in the task JSON.
- Use the configured ref for diff discovery; default to `HEAD` unless the task explicitly requests another ref.
- Record auth as a mode and notes, not raw credentials.
- Store project-specific tokens in the project input directory, not in one global `.env`.
- Keep output paths under `outputs/projects/<project-id>/tasks/<task-id>/` unless the task explicitly requests another output directory.
