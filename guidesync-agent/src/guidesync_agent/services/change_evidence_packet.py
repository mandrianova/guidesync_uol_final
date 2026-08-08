from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from guidesync_agent.agent_runtime.code_change import (
    ChangeEvidenceBudget,
    CodeChangeAnalysisRequest,
    CodeChangeKnowledgeHit,
    CodeChangeReferenceSnippet,
)
from guidesync_agent.tools.knowledge import KnowledgeBaseSearchRequest, search_knowledge_base
from guidesync_agent.tools.repository_filesystem import (
    context_from_project,
    search_files,
    virtual_root_path,
)

CHANGE_EVIDENCE_BUDGET = ChangeEvidenceBudget()
MAX_REFERENCE_SNIPPETS_PER_SYMBOL = 4
MAX_KNOWLEDGE_MATCH_CHARS = 500

CHANGED_DECLARATION_PATTERNS = (
    re.compile(r"^[+-]\s*(?:async\s+def|def|class)\s+([A-Za-z_]\w*)", re.MULTILINE),
    re.compile(
        r"^[+-]\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)",
        re.MULTILINE,
    ),
    re.compile(
        r"^[+-]\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)",
        re.MULTILINE,
    ),
    re.compile(
        r"^[+-]\s*(?:(?:public|private|protected|static|final)\s+)*"
        r"(?:class|interface|enum|record)\s+([A-Za-z_]\w*)",
        re.MULTILINE,
    ),
)


@dataclass(frozen=True)
class ChangeEvidenceBuildContext:
    project_id: str
    repository_id: str
    goal: str
    audience: str


@dataclass(frozen=True)
class PreparedChangeEvidence:
    changed_symbols: list[str]
    related_references: list[CodeChangeReferenceSnippet]
    knowledge_hits: list[CodeChangeKnowledgeHit]
    budget: ChangeEvidenceBudget = field(default_factory=ChangeEvidenceBudget)


def build_change_evidence(
    context: ChangeEvidenceBuildContext,
    requests: list[CodeChangeAnalysisRequest],
) -> PreparedChangeEvidence:
    symbols = changed_declaration_symbols(requests)[: CHANGE_EVIDENCE_BUDGET.max_changed_symbols]
    return PreparedChangeEvidence(
        changed_symbols=symbols,
        related_references=preload_reference_context(context, symbols, requests),
        knowledge_hits=preload_knowledge_context(context, symbols, requests),
    )


def preload_reference_context(
    context: ChangeEvidenceBuildContext,
    symbols: list[str],
    requests: list[CodeChangeAnalysisRequest],
) -> list[CodeChangeReferenceSnippet]:
    if not symbols:
        return []
    filesystem_context = context_from_project(context.project_id)
    root_path = virtual_root_path(context.repository_id)
    changed_paths = {request.path for request in requests}
    snippets: list[CodeChangeReferenceSnippet] = []
    seen_refs: set[str] = set()
    for symbol in symbols:
        result = search_files(
            filesystem_context,
            root_path,
            symbol,
            exclude_patterns=[".git/**", "*.lock"],
        )
        if result.error is not None:
            continue
        entries = sorted(
            result.entries,
            key=lambda entry: (
                entry.get("relative_path") in changed_paths,
                str(entry.get("relative_path", "")),
                int(entry.get("line_number", 0)),
            ),
        )
        append_symbol_references(symbol, entries, snippets, seen_refs)
        if len(snippets) >= CHANGE_EVIDENCE_BUDGET.max_reference_snippets:
            break
    return snippets


def append_symbol_references(
    symbol: str,
    entries: list[dict[str, object]],
    snippets: list[CodeChangeReferenceSnippet],
    seen_refs: set[str],
) -> None:
    symbol_count = 0
    for entry in entries:
        snippet = reference_snippet(symbol, entry)
        if snippet is None or snippet.evidence_ref in seen_refs:
            continue
        snippets.append(snippet)
        seen_refs.add(snippet.evidence_ref)
        symbol_count += 1
        if (
            symbol_count >= MAX_REFERENCE_SNIPPETS_PER_SYMBOL
            or len(snippets) >= CHANGE_EVIDENCE_BUDGET.max_reference_snippets
        ):
            return


def preload_knowledge_context(
    context: ChangeEvidenceBuildContext,
    symbols: list[str],
    requests: list[CodeChangeAnalysisRequest],
) -> list[CodeChangeKnowledgeHit]:
    query_terms = [
        *symbols,
        *(Path(request.path).stem for request in requests),
        context.goal,
    ]
    query = " ".join(dedupe_terms(query_terms))[:500]
    if not query or CHANGE_EVIDENCE_BUDGET.max_knowledge_hits == 0:
        return []
    results = search_knowledge_base(
        KnowledgeBaseSearchRequest(
            project_id=context.project_id,
            query=query,
            audience=context.audience,
            keyphrases=symbols,
            limit=CHANGE_EVIDENCE_BUDGET.max_knowledge_hits,
        )
    )
    return [
        CodeChangeKnowledgeHit(
            node_id=result.node.id,
            path=result.chunk.path if result.chunk else result.node.path,
            heading=result.chunk.heading if result.chunk else None,
            matched_text=result.matched_text[:MAX_KNOWLEDGE_MATCH_CHARS],
            score=result.score,
            evidence_ref=f"knowledge:{result.node.id}",
        )
        for result in results
    ]


def changed_declaration_symbols(requests: list[CodeChangeAnalysisRequest]) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for request in requests:
        for pattern in CHANGED_DECLARATION_PATTERNS:
            for match in pattern.finditer(request.evidence.diff):
                symbol = match.group(1)
                if symbol in seen or symbol.startswith("__"):
                    continue
                seen.add(symbol)
                symbols.append(symbol)
    return symbols


def reference_snippet(
    symbol: str,
    entry: dict[str, object],
) -> CodeChangeReferenceSnippet | None:
    path = entry.get("relative_path")
    line_number = entry.get("line_number")
    preview = entry.get("preview")
    evidence_ref = entry.get("evidence_ref")
    if not (
        isinstance(path, str)
        and isinstance(line_number, int)
        and isinstance(preview, str)
        and isinstance(evidence_ref, str)
    ):
        return None
    return CodeChangeReferenceSnippet(
        symbol=symbol,
        path=path,
        line_number=line_number,
        preview=preview,
        evidence_ref=evidence_ref,
    )


def dedupe_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return terms
