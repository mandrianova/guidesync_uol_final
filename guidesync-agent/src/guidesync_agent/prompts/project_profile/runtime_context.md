# Project Profile Runtime Context

Explore repository evidence with the available repository tools and return the final
`ProjectProfileAgentOutput` only when the project taxonomy is evidence-backed.

The JSON that follows is task context, not a tool-call protocol. Do not return a custom action
wrapper. Use the available repository tools when more evidence is needed.

Rules:

- Call repository tools when evidence is incomplete instead of guessing from project settings.
- Return final output through the provided structured output schema.
- `ProjectTaxonomy.categories` are documentation categories for grouping, routing, searching, and
  placing documentation updates, not arbitrary product or code categories.
- `ProjectTaxonomy.categories`, `components`, `workflows`, `documentation_areas`, and
  `domain_terms` are arrays of strings, not objects.
- For each selected taxonomy value, include `taxonomy.evidence_refs` with `kind`, `value`,
  `reason`, and repository `evidence_refs` copied from inspected tool output.
- `profile_evidence` paths must come from inspected repository files or search results.
