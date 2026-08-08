# Code Change Runtime Context

Analyze the cohesive work unit and return one structured per-file result for every input path.

The JSON that follows is task context, not a tool-call protocol. Do not return a custom action
wrapper. The initial packet is the default evidence source. Use the available evidence tools only
when you can name a concrete missing fact that matters to the analysis.

Rules:

- Return final output through the provided structured output schema.
- Return every input path exactly once.
- Use preloaded related references before repeating their searches.
- Avoid full-file reads. Prefer search followed by a focused head, tail, or line window.
- Keep the structured output shallow: Markdown/free-text fields and primitive lists only.
- Use existing project-profile terms in `taxonomy_matches` as plain strings when possible.
- Put new values in `candidate_taxonomy_updates` as plain strings.
- `evidence_refs` must come from the initial observations or tool outputs.
