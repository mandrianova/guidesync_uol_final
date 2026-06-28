# Code Change Runtime Context

Analyze raw code changes and repository context with the available evidence tools, then return
`CodeChangeAnalysis`.

The JSON that follows is task context, not a tool-call protocol. Do not return a custom action
wrapper. Use available evidence tools when the initial diff or file window is insufficient.

Rules:

- Return final output through the provided structured output schema.
- `taxonomy_matches` items use kind and value fields (`kind`, `value`); do not use `category` or
  `name` keys.
- Use existing project-profile documentation categories for category matches.
- `kind: "category"` matches and category updates refer to documentation categories from the
  project profile, not arbitrary product or code categories.
- Put new values in `candidate_taxonomy_updates`.
- `evidence_refs` must come from the initial observations or tool outputs.
