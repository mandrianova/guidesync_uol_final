# Screenshot Planner

Plan task-level UI screenshots only when the run requests `optional` or `required` screenshots.

Inputs:

- task interface URL;
- run goal;
- per-file change summaries;
- documentation edit plan or changed documentation paths.

Return compact JSON with a scenario name, URL, viewport, expected visible text, and any required
interaction steps. Screenshots are evidence: avoid decorative captures, blank pages, or pages that
do not match the task.
