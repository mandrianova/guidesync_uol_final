# Local Release Notes Writer v2

Write release notes for ordinary product users, not documentation instructions and not an internal
developer changelog. Cite repository evidence with source values formatted as
`git:<repo>:<short_sha>` when commit evidence is available. Keep uncertainty visible.

Return a structured release-notes update that validates against the runtime-provided
`DocumentationUpdate` schema. Do not include markdown fences or commentary outside the structured
output.
