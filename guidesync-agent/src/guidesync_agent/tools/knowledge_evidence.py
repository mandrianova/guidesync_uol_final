from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic_ai import RunContext

from guidesync_agent.schemas import KnowledgeSearchResult

MODEL_KNOWLEDGE_MAX_CONTENT_CHARS = 12_000


class SelectedKnowledgeEvidence(BaseModel):
    evidence_ref: str
    node_id: str
    path: str
    heading: str | None = None
    content: str
    content_hash: str
    source_commit: str | None = None
    taxonomy_version: str | None = None
    score: float


def select_knowledge_evidence(
    results: list[KnowledgeSearchResult],
) -> list[SelectedKnowledgeEvidence]:
    """Build the bounded, hash-identified context exposed to the synthesis agent."""
    selected: list[SelectedKnowledgeEvidence] = []
    seen_refs: set[str] = set()
    for result in results:
        path = result.chunk.path if result.chunk and result.chunk.path else result.node.path
        content_hash = result.node.content_hash
        if not path or not content_hash:
            continue
        evidence_ref = f"knowledge:{result.node.id}"
        if evidence_ref in seen_refs:
            continue
        source_commit = result.node.metadata.get("commit_sha")
        selected.append(
            SelectedKnowledgeEvidence(
                evidence_ref=evidence_ref,
                node_id=result.node.id,
                path=path,
                heading=result.chunk.heading if result.chunk else result.node.name,
                content=truncate_knowledge_content(
                    result.chunk.text if result.chunk else result.matched_text
                ),
                content_hash=content_hash,
                source_commit=source_commit if isinstance(source_commit, str) else None,
                taxonomy_version=result.diagnostics.taxonomy_version,
                score=result.score,
            )
        )
        seen_refs.add(evidence_ref)
    return selected


def register_knowledge_evidence_tools(agent: Any) -> None:
    @agent.tool
    def list_knowledge_context(ctx: RunContext[Any]) -> list[dict[str, Any]]:
        """List the preselected, hash-identified knowledge references for this run."""
        ctx.deps.tool_calls += 1
        refs = [item.evidence_ref for item in ctx.deps.selected_knowledge]
        ctx.deps.knowledge_access_events.append(
            {
                "attempt": ctx.deps.knowledge_attempt,
                "action": "list",
                "evidence_refs": refs,
            }
        )
        return [knowledge_manifest_item(item) for item in ctx.deps.selected_knowledge]

    @agent.tool
    def read_knowledge_context(
        ctx: RunContext[Any],
        evidence_ref: str,
    ) -> dict[str, Any]:
        """Read one bounded preselected knowledge item by its exact evidence reference."""
        ctx.deps.tool_calls += 1
        item = next(
            (
                candidate
                for candidate in ctx.deps.selected_knowledge
                if candidate.evidence_ref == evidence_ref
            ),
            None,
        )
        event: dict[str, Any] = {
            "attempt": ctx.deps.knowledge_attempt,
            "action": "read",
            "evidence_ref": evidence_ref,
            "found": item is not None,
        }
        if item is None:
            ctx.deps.knowledge_access_events.append(event)
            return {"found": False, "evidence_ref": evidence_ref}
        ctx.deps.knowledge_read_refs.add(item.evidence_ref)
        event.update(
            {
                "content_hash": item.content_hash,
                "source_commit": item.source_commit,
            }
        )
        ctx.deps.knowledge_access_events.append(event)
        return {
            "found": True,
            **knowledge_manifest_item(item),
            "content": item.content,
        }


def knowledge_manifest_item(item: SelectedKnowledgeEvidence) -> dict[str, Any]:
    return {
        "evidence_ref": item.evidence_ref,
        "path": item.path,
        "heading": item.heading,
        "content_hash": item.content_hash,
        "source_commit": item.source_commit,
        "taxonomy_version": item.taxonomy_version,
        "score": item.score,
    }


def truncate_knowledge_content(value: str) -> str:
    if len(value) <= MODEL_KNOWLEDGE_MAX_CONTENT_CHARS:
        return value
    suffix = "\n...[truncated]"
    cutoff = MODEL_KNOWLEDGE_MAX_CONTENT_CHARS - len(suffix)
    return f"{value[:cutoff].rstrip()}{suffix}"
