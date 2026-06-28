# Code Change Runtime Context

Analyze raw code changes and repository context with the available evidence tools, then return
`CodeChangeAnalysisModelOutput`.

The JSON that follows is task context, not a tool-call protocol. Do not return a custom action
wrapper. Use available evidence tools when the initial diff or file window is insufficient.

Rules:

- Return final output through the provided structured output schema.
- Keep the structured output shallow: Markdown/free-text fields and primitive lists only.
- Use existing project-profile terms in `taxonomy_matches` as plain strings when possible.
- Put new values in `candidate_taxonomy_updates` as plain strings.
- `evidence_refs` must come from the initial observations or tool outputs.
