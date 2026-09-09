# Iteration 01 - Recent Ardor Diff To Visual Guide Update

## Objective

Find one recent user-facing Ardor UI change and use it to test the GuideSync MVP loop.

## Planned Steps

1. Inspect the four scoped Ardor repositories and record current branch/status.
2. Pull or fetch latest changes from Git for the scoped repositories.
3. Identify changes on `main` from the last month in those repositories.
4. Pick one change that likely affects a user-facing workflow.
5. Determine which UI project and local start command are needed.
6. Launch the UI locally.
7. Capture screenshots for the affected workflow.
8. Create or identify an existing guide that is stale relative to the current UI.
9. Generate an updated markdown guide and a short change report.
10. Compare the generated update against a baseline that does not use live UI screenshots.

## Reusable Agent Assets

Manual discovery steps should be captured as scripts/skills as they are performed.

Created initial reusable assets:

- `project/guidesync-mvp/agent/pipeline.md`
- `project/guidesync-mvp/agent/skills/task-input/SKILL.md`
- `project/guidesync-mvp/agent/skills/environment-setup/SKILL.md`
- `project/guidesync-mvp/agent/skills/repo-scope/SKILL.md`
- `project/guidesync-mvp/agent/skills/recent-diff-discovery/SKILL.md`
- `project/guidesync-mvp/agent/skills/release-notes/SKILL.md`
- `project/guidesync-mvp/agent/skills/screenshot-plan/SKILL.md`
- `project/guidesync-mvp/agent/skills/ui-launch-scout/SKILL.md`
- `project/guidesync-mvp/agent/skills/browser-capture/SKILL.md`
- `project/guidesync-mvp/agent/skills/doc-generation/SKILL.md`
- `project/guidesync-mvp/inputs/task.schema.json`
- `project/guidesync-mvp/inputs/example-task-domains.json`
- `project/guidesync-mvp/environment.md`
- `project/guidesync-mvp/scripts/repo_status.sh`
- `project/guidesync-mvp/scripts/fetch_scoped_repos.sh`
- `project/guidesync-mvp/scripts/recent_main_commits.sh`
- `project/guidesync-mvp/scripts/show_commit_files.sh`
- `project/guidesync-mvp/scripts/validate_task_input.sh`
- `project/guidesync-mvp/scripts/environment_check.sh`
- `project/guidesync-mvp/scripts/init_run_dirs.sh`
- `project/guidesync-mvp/scripts/create_screenshot_plan_stub.sh`

## Selection Criteria For The First Diff

Prefer a change that:

- is in `solutions-ui` or clearly affects `solutions-ui` behaviour;
- touches labels, navigation, forms, onboarding, settings or user-visible workflow state;
- can be reproduced locally without production credentials;
- can be explained in a short guide;
- has a manageable workflow with 3-8 screenshots.

Avoid a change that:

- requires production-only data or secrets;
- is purely backend/internal;
- needs too many services to launch;
- requires a complex role model for the first spike;
- would expose private customer data.

## Notes

- The first iteration should be a spike, not a polished product.
- It is acceptable to use a synthetic stale guide if no existing doc page matches the selected workflow.
- The generated documentation should be reviewable, not automatically published.
- Current best first diff candidate: `solutions-ui` commit `ed59b45` / domains functionality, paired with related backend/artifact-service domain commits.
- Safer backup candidates: workspace permission controls or chat slash commands.

## Scoped Repositories

- `<author-local-project>`
- `<author-local-project>`
- `<author-local-project>`
- `<author-local-project>`

## Local UI Notes

`solutions-ui` scripts:

- `bun run dev` -> Vite on port `3000`
- `bun run start` -> Vite on port `3000`
- `bun run build`
- `bun run test`

Need to inspect environment variables and backend requirements before launching.
