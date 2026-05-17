# Documentation Generation Skill

Use this skill after browser screenshots and UI evidence have been collected.

## Purpose

Generate or update a user-facing guide from the release notes, existing guide, screenshot plan and captured UI evidence.

## Inputs

- existing guide or stale fixture;
- release notes;
- screenshot plan;
- screenshots;
- browser-capture evidence;
- incoming task JSON.

## Outputs

- `outputs/<run>/guide-update.md`
- `outputs/<run>/change-report.md`
- `outputs/<run>/user-guide.html`

Reusable markdown draft command:

```bash
project/guidesync-mvp/scripts/generate_guide_draft.sh \
  outputs/projects/<project-id>/tasks/<task-id>/browser-capture.json \
  outputs/projects/<project-id>/tasks/<task-id>/guide-update.md \
  <existing-guide.md> \
  "<Guide Title>"
```

## Guide Update Requirements

The guide update should include:

- title;
- audience/role;
- prerequisites;
- ordered steps;
- screenshot references;
- expected result;
- troubleshooting or review notes where useful.
- requirements and limitations;
- highlighted fields, buttons and statuses in screenshots;
- a browsable visual guide artifact, not only a raw Markdown file.

## Change Report Requirements

The change report should include:

- what changed in the product;
- which guide section was affected;
- what the agent changed;
- evidence used;
- uncertainty and human-review checklist.

## Rules

- Propose documentation changes for human review.
- Do not claim the guide is final if screenshots or auth were incomplete.
- Keep screenshot paths relative to the MVP workspace.
- Treat Markdown as an intermediate source. The final user artifact should be visually scannable, include screenshots or media, and support direct browser review.
- Mask, crop or replace private data before using screenshots in user-facing documentation.
- Do not invent steps that were not supported by capture evidence. Put missing coverage into the review checklist.
