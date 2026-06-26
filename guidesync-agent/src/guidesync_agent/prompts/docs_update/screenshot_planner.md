# Screenshot Planner

Plan task-level UI screenshots only when the run requests `optional` or `required` screenshots.

Inputs:

- task interface URL;
- run goal;
- per-file change summaries;
- documentation edit plan or changed documentation paths.

Return structured screenshot-plan output using the runtime-provided schema. Screenshots are
evidence: avoid decorative captures, blank pages, or pages that do not match the task.
