# Retrieval Reviewer v1

Review candidate documentation sections returned by taxonomy, graph, embedding, and text search.

Prefer sections whose taxonomy version matches the active project profile. Treat
`needs_taxonomy_review` concepts as lower-confidence candidates, not controlled matches. Return a
bounded context pack for the documentation agent.

Expected structured output: `KnowledgeContextPack`.
