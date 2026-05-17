# GuideSync Agent Pipeline

This document defines the intended MVP agent workflow.

## Pipeline Summary

```text
Incoming task
  -> collect product diffs
  -> summarise change / draft release notes
  -> create screenshot plan
  -> launch browser and execute screenshot scripts
  -> generate or update documentation
  -> rank announcement features
  -> review generated user-facing copy
  -> produce agent run report
```

The agent should treat each stage as a skill with explicit inputs and outputs. This makes the MVP reproducible and easier to evaluate.

## Stage 1 - Incoming Task Intake

Input:

- task JSON matching `project/guidesync-mvp/inputs/task.schema.json`

Output:

- validated task context;
- resolved repository paths;
- output directories created;
- initial run metadata.

Skill:

- `agent/skills/task-input/SKILL.md`

Script:

- `scripts/validate_task_input.sh`

## Stage 2 - Collect Product Diffs

Input:

- validated task;
- repository list;
- time window or explicit commit/PR.

Output:

- list of relevant commits;
- changed files;
- candidate user-facing changes;
- selected diff target.

Skill:

- `agent/skills/recent-diff-discovery/SKILL.md`

Scripts:

- `scripts/repo_status.sh`
- `scripts/fetch_scoped_repos.sh`
- `scripts/recent_main_commits.sh`
- `scripts/show_commit_files.sh`

MVP note:

- Prefer analysing `origin/main` without mutating local working copies.

## Stage 3 - Draft Change Summary / Release Notes

Input:

- selected diff target;
- changed files;
- commit messages;
- optional task/issue context;
- optional code snippets from changed files.

Output:

- concise release-note style summary;
- user-visible change hypothesis;
- affected roles/workflows;
- documentation impact hypothesis.

Skill:

- `agent/skills/release-notes/SKILL.md`

Output file:

- `outputs/<run>/release-notes.md`

## Stage 4 - Create Screenshot Plan

Input:

- task context;
- release notes;
- changed UI files/routes;
- existing/stale guide;
- UI URL and auth mode.

Output:

- screenshot plan with ordered steps;
- route hints;
- selectors or natural-language actions;
- expected screenshots;
- fallback/manual steps if automation fails.
- interaction-based capture steps for UI-visible changes without new routes, for example typing `/` or `@` in a chat composer.
- screenshot QA rules, rejected page states, retry routes/waits, and crop/highlight instructions for the final announcement.

Skill:

- `agent/skills/screenshot-plan/SKILL.md`

Output file:

- `outputs/<run>/screenshot-plan.json`

## Stage 5 - Launch Browser And Capture Screenshots

Input:

- screenshot plan;
- UI launch configuration;
- auth mode;
- output screenshot directory.

Output:

- screenshots;
- page URLs;
- visible text / accessibility snapshots;
- browser execution notes;
- failures/blockers.

Skills:

- `agent/skills/environment-setup/SKILL.md`
- `agent/skills/ui-launch-scout/SKILL.md`
- `agent/skills/browser-capture/SKILL.md`

Output files:

- `screenshots/<run>/*.png`
- `outputs/<run>/browser-capture.json`

## Stage 6 - Generate Or Update Documentation

Input:

- existing guide or stale fixture;
- release notes;
- screenshot plan;
- captured screenshots;
- UI text/accessibility snapshots.

Output:

- updated markdown guide proposal;
- screenshot references;
- documentation diff or replacement section;
- review notes and confidence.

Skill:

- `agent/skills/doc-generation/SKILL.md`

Output files:

- `outputs/<run>/guide-update.md`
- `outputs/<run>/change-report.md`

## Stage 7 - Rank Announcement Features

Input:

- localized feature payload;
- source change score;
- browser capture results;
- screenshots;
- generated user benefit, examples, and steps.

Output:

- `announcement_priority` for every selected feature:
  - rank;
  - role (`spotlight` or `supporting`);
  - score;
  - rationale.

Rule:

- Do not hardcode product-specific feature names as the priority rule. Rank from the available evidence: user-facing outcome, successful UI evidence, complete examples/steps, route or interaction coverage, and source change score.

## Stage 8 - Generated Copy Review

Input:

- generated HTML release notes;
- localized feature payload;
- browser capture notes;
- screenshot coverage.

Output:

- content review status;
- findings for generic wording, technical leakage, missing benefits, missing examples, and missing screenshots;
- revised payload before final HTML write when deterministic fixes are available.

Output location:

- `release-notes.json` under `content_review`.

## Stage 9 - Agent Run Report

Input:

- generated guide update;
- release notes;
- screenshots;
- browser capture notes;
- content review findings;
- uncertainty markers;
- runtime errors and warnings.

Output:

- short agent report:
  - what the agent did;
  - which artifacts were written;
  - which user-facing updates were included;
  - what problems, warnings, or review findings remain.

Output file:

- `outputs/<run>/agent-report.md`

## MVP Evaluation Hooks

Each run should preserve enough evidence to compare:

- baseline: LLM with stale/existing guide only;
- candidate: LLM with diff/release notes only;
- full GuideSync: diff + release notes + browser screenshots + UI text.

Suggested scoring:

- workflow coverage;
- step correctness;
- UI label accuracy;
- screenshot alignment;
- stale-doc detection;
- human-review usefulness.

## Persistence Approach

For the first end-to-end run, persistence is file-based:

- task input JSON;
- release notes markdown;
- screenshot plan JSON;
- screenshots;
- browser capture JSON;
- guide update markdown;
- content review metadata;
- agent report markdown.

SQLite persistence is deferred until after the first run, when the useful data shape is clearer. Notes are tracked in `project/guidesync-mvp/db/README.md`.
