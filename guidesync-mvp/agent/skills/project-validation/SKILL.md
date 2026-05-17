# Project Validation Skill

Use this skill immediately after running a `project_init` task.

## Purpose

Review the generated project configuration before any release task is run. The init script is a deterministic generator; the agent is responsible for validating whether the generated files make sense for the product.

## Inputs

- `inputs/projects/<project-id>/project.json`
- `inputs/projects/<project-id>/release-task.json`
- `inputs/projects/<project-id>/templates/brand.css`
- `inputs/projects/<project-id>/templates/copy.json`
- `outputs/projects/<project-id>/init-report.json`
- the UI repository referenced by `ui.repository` / `ui.repositories`

## Checks

- `project.json` has the right project id, display name, existing root/repository paths and project-local `branding` / `copy` references.
- `release-task.json` uses the release schema, real repository paths, the intended public or test UI URL, and no legacy guide fields.
- `brand.css` contains plausible project colors and does not look like a random unrelated asset palette.
- `copy.json` is valid JSON and contains only project-specific overrides; generic copy belongs in the base catalog.
- Logo selection is plausible:
  - accept only if `init-report.logo_status` is `accepted` and the top candidate is clearly a logo/brand/wordmark for this product;
  - if `logo_status` is `fallback-generated`, treat this as a warning, not a failure;
  - if the top candidates are random illustrations, icons, demo assets, screenshots, or unrelated product logos, remove the generated logo asset and leave fallback branding or ask for the correct asset.
- Init report is under `outputs/projects/<project-id>/init-report.json`, not inside `inputs/`.

## Output

Write a short validation summary in the agent response and, when useful, append a `validation` object to `outputs/projects/<project-id>/init-report.json` with:

- `status`: `ok`, `needs-review`, or `failed`;
- `errors`: blocking issues that prevent release runs;
- `warnings`: issues that should be reviewed but do not block a run;
- `fixes_applied`: files the agent edited after validation.

## Rules

- Do not make the shell init script decide whether a logo is semantically correct; this is an agent review step.
- Do not keep a generated logo if the repo likely has no real logo and the fallback would misrepresent the product.
- Do not put validation reports under `inputs/`.
