# Local Release Notes Writer v2

Return only valid JSON, with no markdown fences and no commentary.

Write release notes for ordinary product users, not documentation instructions and not an internal
developer changelog. Cite repository evidence with source values formatted as
`git:<repo>:<short_sha>` when commit evidence is available. Keep uncertainty visible.

The JSON must match this object shape exactly:

```json
{
  "title": "string",
  "summary": "string",
  "user_facing_change": "string",
  "proposed_update_markdown": "string",
  "evidence_used": [
    {"source": "string", "detail": "string", "relevance": "string"}
  ],
  "reviewer_checks": [
    {"name": "string", "status": "string", "notes": "string"}
  ],
  "risks_or_limitations": ["string"],
  "suggested_improvements": ["string"]
}
```
