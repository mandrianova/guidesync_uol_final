# Project Profile Runtime Context

Explore repository evidence with the available read-only repository tools and
return the final `ProjectProfileAgentOutput`.

The JSON that follows is task context, not a tool-call protocol. Do not return a
custom action wrapper. Use tools when evidence is incomplete instead of guessing
from project settings.

Rules:

- Keep the structured output shallow.
- Put rich repeated detail in Markdown string fields.
- Use `core_concepts` only for a simple list of important project concepts.
- Use `categories` only for a short list of user-facing documentation content
  areas derived from actual repository evidence.
- Do not emit taxonomy objects, evidence objects, aliases, workflows, key terms,
  repository maps, source refs, or model metadata.
