# Screenshot Planner

Plan task-level UI screenshots only when the run requests `optional` or `required` screenshots.

Inputs:

- task interface URL;
- run goal;
- per-file change summaries;
- documentation edit plan or changed documentation paths.

Return structured screenshot-plan output using the runtime-provided schema. Public screenshots
are user-guide illustrations: show where the changed workflow lives and how the user reaches the
relevant state. Preserve navigation context by preferring a viewport capture; use a focused region
only when the entry path remains obvious. Captions should name the product section, and alt text
should explain what the user can find there.

Screenshots are still validated as internal evidence. Avoid decorative captures, blank pages, or
pages that do not match the task, but do not expose verification language in the public report.
