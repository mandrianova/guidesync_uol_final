# Iteration 02 - Generic Release Notes Agent

## Objective

Move the MVP from a one-off Ardor experiment to a reusable GuideSync agent that can initialize projects, run release-note tasks for different repositories, capture UI evidence with Playwright, and produce user-facing HTML release announcements.

## What Changed

### Task Model

- Split task input into reusable `project_init` and `release` task shapes.
- Made release tasks accept a project id, repository list, period, UI URL/launch settings, auth settings, languages and output settings.
- Added project-specific `.env` convention under `inputs/projects/<project-id>/` instead of a single shared runtime env.
- Kept Ardor as an example project and added a Signals example to test that the pipeline is not tied to one product.
- Removed obsolete task scripts and schemas that represented the first one-off Domains spike.

### Agent Orchestration

- Reworked the pipeline so the agent owns the workflow decisions and uses scripts as tools.
- Added project initialization as a first-class task.
- Added project validation as an agent responsibility instead of shell-only validation.
- Kept only the active skills needed for the current workflow:
  - `task-input`
  - `project-init`
  - `project-validation`
  - `release-notes`
- Updated the release-notes skill so the agent treats scripts as evidence collectors, not as a complete publishing decision.

### Project Initialization

- Added init support from JSON task input.
- Initialization now inspects UI repositories, not just a deployed URL, to discover branding signals.
- Generated project files are written under `inputs/projects/<project-id>/`.
- Init reports are written under `outputs/projects/<project-id>/`, not into inputs.
- Logo detection now records candidates and accepts a logo only when the repository evidence is strong enough.
- The pipeline now expects the agent to validate init output, including logo correctness, colors, language hints, generated CSS and release-task defaults.

### Release Notes Generation

- Moved final HTML rendering to a Jinja template.
- Added project-specific template CSS and copy catalogs so brand styling and feature copy are not hard-coded into Python.
- Removed Ardor-specific copy and route overrides from base scripts.
- Added language flow: English is generated first, then localized outputs are produced when project/task/output languages require them.
- Changed copy rules toward release-announcement style: what changed, why it helps, where to find it, and practical examples.
- Removed user-facing code/file references from the HTML output and kept technical evidence in JSON/report artifacts.

### Feature Prioritization And Evidence

- Added evidence collection from commits, changed files, file stats and readable diff hints.
- Added `change-evidence.json` so the agent can inspect commit bodies, UI labels, product copy hints and file-level evidence before writing publishable copy.
- Added copy-status markers so vague issue/PR-style commits can be marked `agent_required` instead of being published as weak fallback cards.
- Updated pipeline notes to require agent review when generated copy is too technical or too low-signal.

### Screenshots

- Kept Playwright as the repeatable screenshot path.
- Added support for UI launch settings, including Docker-based launch modes to avoid local port conflicts.
- Changed screenshot planning so it is not limited to newly discovered routes.
- Added interaction-oriented capture expectations for UI surfaces without routes, such as chat composer flows with `/` or `@`.
- Added screenshot QA expectations: reject empty/404 states, retry where possible, and crop/highlight relevant UI for the final announcement.

### Output Structure

- Outputs are separated by project and task:
  - `outputs/projects/<project-id>/init-report.json`
  - `outputs/projects/<project-id>/tasks/<task-id>/release-notes.html`
  - `outputs/projects/<project-id>/tasks/<task-id>/release-notes.<lang>.html`
  - `outputs/projects/<project-id>/tasks/<task-id>/release-notes.json`
  - `outputs/projects/<project-id>/tasks/<task-id>/change-evidence.json`
  - `outputs/projects/<project-id>/tasks/<task-id>/agent-report.md`
- Generated outputs are kept out of the main code path so one run does not affect the next run.

### Local Task UI

- Added a small local GuideSync UI.
- The UI can create `project_init` and `release` task JSON files.
- It can run the current dispatcher, `scripts/run_task.sh`.
- It shows generated JSON, run output and links to generated HTML, reports, JSON and screenshots.
- It lists existing projects from `inputs/projects/` and recent artifacts from `outputs/projects/`.

## Current State

The MVP is now a reusable local agent prototype rather than an Ardor-only script. It supports multiple projects, per-project configuration, per-task outputs, project initialization, release-note generation, Playwright-based UI evidence and a simple task creation UI.

The main remaining weakness is still content judgment. The scripts now preserve more evidence, but the agent must actively use that evidence to write product-level copy. The pipeline should continue moving away from deterministic fallback text and toward agent-reviewed release announcements.

## Validation Completed

- Checked Python syntax for the UI server.
- Checked shell syntax for `run_ui.sh`.
- Verified the `guidesync-ui` console entrypoint.
- Started the local UI at `http://127.0.0.1:8765`.
- Verified `/api/projects` returns project data, including nested `project.json` format.
- Opened the UI with Playwright and verified the page title and release-task screen render.
- Smoke-tested task JSON creation through the local API.

## Known Gaps

- The local UI is intentionally simple and does not yet validate every schema field client-side.
- Long-running task execution is synchronous in the UI API, so the browser waits for the process to finish.
- There is no run history database yet; the UI reads files from `inputs/` and `outputs/`.
- Screenshot editing/highlighting is rule-based and should be improved with better crop target selection.
- The agent still needs stronger review loops for narrative quality, feature prioritization and visual polish.
- Project initialization can find candidate logos/colors, but human or agent validation remains necessary when repository branding is sparse.

## Recommended Next Steps

1. Add a run-history layer.
   Store task runs, status, logs and artifact paths in a small SQLite database so the UI can show progress and previous results without scanning folders.

2. Make task execution asynchronous.
   Return a run id immediately, stream logs or poll status, and allow the UI to stay responsive during long Playwright/repository runs.

3. Add schema-aware UI validation.
   Validate task forms against `project-init-task.schema.json` and `release-task.schema.json` before saving.

4. Strengthen agent copy review.
   Add a final review pass that scores the generated HTML for user value, clarity, UI terminology, release-announcement tone, missing examples and technical leakage.

5. Improve screenshot QA and editing.
   Add more robust relevance checks, crop target selection, highlight overlays and retry logic before screenshots enter the HTML.

6. Improve project initialization.
   Let the project-init agent compare logo candidates against repository usage, page metadata and UI screenshots before accepting a logo.

7. Add integration fixtures.
   Keep small fixture repositories/tasks for `project_init` and `release` so changes can be tested without Ardor or Signals access.

8. Package the UI workflow.
   Add a single documented command for local use and later decide whether the UI should run as a Docker service next to the agent runtime.
