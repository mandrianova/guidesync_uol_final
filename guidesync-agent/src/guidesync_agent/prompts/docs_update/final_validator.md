# Final Validator v1

Validate the generated documentation update, evidence refs, taxonomy usage, edit plan, patch, and
post-edit knowledge annotation metadata.

Return findings rather than silently accepting missing evidence, unsupported taxonomy categories,
invalid JSON, unsafe documentation paths, missing prompt metadata, or no-op edits.

Expected structured output: `ValidationFindingsModelOutput`.

Keep the structured output shallow. Put findings in `findings_markdown`, report aggregate
`error_count` and `warning_count`, and cite evidence as plain strings in `evidence_refs`.
