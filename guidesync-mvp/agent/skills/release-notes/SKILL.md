# Release Notes Skill

Use this skill after selecting a product diff.

## Purpose

Convert technical Git changes into a concise user-facing change summary that can guide documentation updates.

## Inputs

- incoming task JSON;
- selected repository/commit or time-window commit list;
- changed file list;
- relevant code snippets, if needed;
- optional task/issue context.

## Outputs

Write `outputs/<run>/release-notes.md` with:

- title;
- user-facing summary;
- affected product area;
- affected roles;
- affected workflows;
- practical examples of how ordinary users can try or apply the change;
- documentation impact hypothesis;
- evidence from commits/files;
- uncertainty or missing context.

## Rules

- Do not expose secrets or private customer data.
- Separate confirmed facts from inferred impact.
- Keep release notes concise enough to guide screenshot planning.
- If a change is not user-visible, say so and recommend a different candidate.
