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
    re.compile(
        r"^[+]\s*([A-Za-z_]\w*)\s*(?::[^=]+)?=",
        re.MULTILINE,
    ),
)


@dataclass(frozen=True)
class ChangeEvidenceBuildContext:
    project_id: str
    repository_id: str
    goal: str
    audience: str
    knowledge_context_enabled: bool = True


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
    entries_by_symbol: dict[str, list[dict[str, object]]] = {}
    for symbol in symbols:
        result = search_files(
            filesystem_context,
            root_path,
            symbol,
            exclude_patterns=[".git/**", "*.lock"],
        )
        if result.error is not None:
            continue
        entries_by_symbol[symbol] = sorted(
            result.entries,
            key=lambda entry: (
                is_symbol_declaration(symbol, entry),
                entry.get("relative_path") not in changed_paths,
                str(entry.get("relative_path", "")),
                int(entry.get("line_number", 0)),
            ),
        )
    return interleave_symbol_references(entries_by_symbol)


def interleave_symbol_references(
    entries_by_symbol: dict[str, list[dict[str, object]]],
) -> list[CodeChangeReferenceSnippet]:
    candidates = {
        symbol: [
            snippet
            for entry in entries[:MAX_REFERENCE_SNIPPETS_PER_SYMBOL]
            if (snippet := reference_snippet(symbol, entry)) is not None
        ]
        for symbol, entries in entries_by_symbol.items()
    }
    snippets: list[CodeChangeReferenceSnippet] = []
    seen_refs: set[str] = set()
    for index in range(MAX_REFERENCE_SNIPPETS_PER_SYMBOL):
        for symbol in entries_by_symbol:
            symbol_candidates = candidates[symbol]
            if index >= len(symbol_candidates):
                continue
            snippet = symbol_candidates[index]
            if snippet.evidence_ref in seen_refs:
                continue
            snippets.append(snippet)
            seen_refs.add(snippet.evidence_ref)
            if len(snippets) >= CHANGE_EVIDENCE_BUDGET.max_reference_snippets:
                return snippets
    return snippets


def preload_knowledge_context(
    context: ChangeEvidenceBuildContext,
    symbols: list[str],
    requests: list[CodeChangeAnalysisRequest],
) -> list[CodeChangeKnowledgeHit]:
    if not context.knowledge_context_enabled:
        return []
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
    symbols_by_file = [declaration_symbols(request) for request in requests]
    symbols: list[str] = []
    seen: set[str] = set()
    max_symbols = max((len(file_symbols) for file_symbols in symbols_by_file), default=0)
    for index in range(max_symbols):
        for file_symbols in symbols_by_file:
            if index >= len(file_symbols):
                continue
            symbol = file_symbols[index]
            if symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
    return symbols


def declaration_symbols(request: CodeChangeAnalysisRequest) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for pattern in CHANGED_DECLARATION_PATTERNS:
        for match in pattern.finditer(request.evidence.diff):
            symbol = match.group(1)
            if symbol in seen or symbol.startswith("__"):
                continue
            seen.add(symbol)
            symbols.append(symbol)
    return symbols


def is_symbol_declaration(symbol: str, entry: dict[str, object]) -> bool:
    preview = entry.get("preview")
    if not isinstance(preview, str):
        return False
    declaration = rf"\b(?:def|class|function)\s+{re.escape(symbol)}\b"
    return re.search(declaration, preview) is not None


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
