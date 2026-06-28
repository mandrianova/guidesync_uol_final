# Documentation Edit Planner v1

Plan the concrete documentation edit before writing files.

Choose one of the allowed operations: update an existing matching section, add a focused section to
an existing document, or create a new document under the configured docs path. Require evidence refs
for every planned edit. Do not create generic append-only `GuideSync Documentation Update` blocks.

Expected structured output: `DocumentationEditPlanModelOutput`.

Keep the structured output shallow. Put the concrete edit plan in `plan_markdown`, cite evidence as
plain strings in `evidence_refs`, and do not return lists of edit objects.
