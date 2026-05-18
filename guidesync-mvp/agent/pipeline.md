# GuideSync Agent Pipeline

This document defines the active GuideSync MVP workflow.

## Operating Model

GuideSync is skill-led. Skills decide what to run, how to interpret results, and which validation gates pass. Shell scripts are tools: they collect data, generate deterministic files, or dispatch the Python runtime, but they do not replace agent review.

Primary dispatcher tool from the CM3070 project root:

```bash
project/guidesync-mvp/scripts/run_task.sh <task-json>
```

Supported task kinds:

- project init: `task.type == "project_init"`;
- release task: `period` + `repositories`.

Unsupported task JSON must stop with a clear error. Do not create run directories manually and do not call removed legacy helpers.

## Skill Order

```text
task-input
  -> project-init -> project-validation
  OR
  -> release-notes -> release output review
```

## Intake

Skill:

- `agent/skills/task-input/SKILL.md`

Inputs:

- `inputs/project-init-task.schema.json`
- `inputs/release-task.schema.json`
- project-specific task JSON under `inputs/projects/<project-id>/`

Responsibilities:

- identify task kind;
- confirm required paths and high-level intent;
- choose which tool step to run first;
- use `scripts/run_task.sh <task-json>` as the safe dispatcher for deterministic execution;
- inspect the generated artifacts before deciding the next step;
- do not treat a successful script exit as a completed task.

## Project Init Path

Skills:

- `agent/skills/project-init/SKILL.md`
- `agent/skills/project-validation/SKILL.md`

Tool:

- `scripts/init_project_from_task.sh`, called only through `scripts/run_task.sh`

Inputs:

- project init task JSON;
- UI repository path(s), preferably `ui.repository` or `ui.repositories`;
- optional runtime URL.

Generated files:

- `inputs/projects/<project-id>/project.json`
- `inputs/projects/<project-id>/release-task.json`
- `inputs/projects/<project-id>/templates/brand.css`
- `inputs/projects/<project-id>/templates/copy.json`
- `inputs/projects/<project-id>/assets/logo.*` when accepted or fallback-generated
- `outputs/projects/<project-id>/init-report.json`

Validation responsibilities:

- read the generated files and init report;
- verify repository paths and task shape;
- review logo candidates semantically instead of trusting filename score alone;
- flag fallback logo as `needs-review` when the project appears to have no real logo;
- remove or replace misleading generated assets;
- append validation findings to the init report when useful.

Agent decision points:

- If the discovered logo is not clearly the product logo, remove it or leave fallback branding and record a warning.
- If colors appear to come from a random illustration or unrelated package, adjust `brand.css` from more reliable UI tokens or leave neutral defaults.
- If generated `release-task.json` contains placeholder repositories, replace them from the init task or ask for the missing repo list.
- If the init result is not publishable, do not proceed to release generation.

## Release Path

Skill:

- `agent/skills/release-notes/SKILL.md`

Tools:

- `scripts/run_release_agent.sh`, called only through `scripts/run_task.sh`
- Python runtime in `src/guidesync_mvp/agent.py`
- Python Playwright capture in `src/guidesync_mvp/capture.py`
- Jinja HTML template in `src/guidesync_mvp/templates/release_notes.html`

Inputs:

- release task JSON;
- project config inherited from sibling `project.json`;
- repositories and period;
- optional UI URL/auth configuration;
- project-local brand CSS and copy catalog.

Generated files:

- `outputs/projects/<project-id>/tasks/<task-id>/release-notes.html`
- `outputs/projects/<project-id>/tasks/<task-id>/release-notes.<lang>.html`
- `outputs/projects/<project-id>/tasks/<task-id>/release-notes.json`
- `outputs/projects/<project-id>/tasks/<task-id>/change-evidence.json`
- `outputs/projects/<project-id>/tasks/<task-id>/screenshot-plan.json`
- `outputs/projects/<project-id>/tasks/<task-id>/browser-capture.json`
- `outputs/projects/<project-id>/tasks/<task-id>/agent-report.md`

Review responsibilities:

- verify the HTML reads like a user-facing product announcement;
- use `change-evidence.json` as the source packet for agent-written copy: commit titles, bodies, file stats, changed files and readable diff hints;
- check that screenshots are relevant, cropped/highlighted when possible, and not 404/empty states;
- check that feature priority is evidence-based;
- check that user copy does not expose code paths, commit hashes, or internal implementation names;
- use the agent report to decide whether follow-up fixes are needed.

Agent decision points:

- If screenshot capture misses a user-visible feature, update route/interaction hints and rerun capture.
- If the script marks a change as evidence-only or `agent_required`, do not publish the fallback card. Read the evidence packet and write a product-level explanation manually, or drop the change if the evidence still does not show user impact.
- If copy reads like a technical report, adjust project copy/catalog or generation rules and rerun.
- If generated priority looks wrong, inspect `announcement_priority` evidence and change the ranking logic or inputs before accepting the result.
- If the UI URL is sparse but the repository has UI surfaces, use repository evidence for planning and record the live URL limitation.

## Tool Boundaries

Scripts may:

- route task kinds;
- scan repositories for deterministic signals;
- generate initial files;
- run the release runtime;
- write machine-readable reports.

Skills must:

- validate generated artifacts;
- decide whether discovered assets are semantically correct;
- decide whether screenshots and copy are publishable;
- apply targeted fixes or report blockers.

## Persistence

The MVP remains file-based:

- task input JSON;
- project config and project copy/theme files;
- release payload JSON;
- screenshot plan and capture JSON;
- screenshots;
- HTML release notes;
- agent/init reports.

SQLite persistence is deferred until the useful data shape is clearer. Notes are tracked in `project/guidesync-mvp/db/README.md`.
