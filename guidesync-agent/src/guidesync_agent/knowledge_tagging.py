from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

CAMEL_ACRONYM_BOUNDARY = re.compile(r"([A-Z]+)([A-Z][a-z])")
CAMEL_WORD_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
NON_IDENTIFIER_CHARS = re.compile(r"[^A-Za-z0-9]+")

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "class",
    "const",
    "def",
    "else",
    "export",
    "false",
    "for",
    "from",
    "has",
    "function",
    "if",
    "import",
    "in",
    "interface",
    "is",
    "it",
    "let",
    "new",
    "none",
    "not",
    "null",
    "of",
    "on",
    "or",
    "return",
    "the",
    "this",
    "to",
    "true",
    "type",
    "var",
    "void",
    "was",
    "with",
}

SINGULAR_SUFFIX_EXCEPTIONS = {
    "css",
    "has",
    "his",
    "js",
    "jsx",
    "this",
    "ts",
    "tsx",
    "was",
    "yes",
}

CATEGORY_TERMS = {
    "api": {
        "api",
        "client",
        "endpoint",
        "fetch",
        "handler",
        "http",
        "request",
        "response",
        "rest",
        "route",
        "router",
        "server",
    },
    "auth": {
        "auth",
        "authorization",
        "credential",
        "jwt",
        "login",
        "oauth",
        "permission",
        "session",
        "signin",
        "signup",
        "token",
        "user",
    },
    "config": {
        "config",
        "configuration",
        "docker",
        "env",
        "eslint",
        "json",
        "makefile",
        "package",
        "pyproject",
        "setting",
        "toml",
        "tsconfig",
        "yaml",
        "yml",
    },
    "docs": {
        "doc",
        "docs",
        "documentation",
        "guide",
        "markdown",
        "md",
        "mdx",
        "readme",
        "rst",
    },
    "model-provider": {
        "anthropic",
        "embedding",
        "gemini",
        "llm",
        "model",
        "openai",
        "provider",
        "prompt",
    },
    "storage": {
        "alembic",
        "cache",
        "database",
        "db",
        "migration",
        "postgres",
        "repository",
        "sql",
        "sqlalchemy",
        "store",
        "storage",
        "table",
    },
    "terminal": {
        "bash",
        "cli",
        "command",
        "console",
        "process",
        "shell",
        "terminal",
        "tty",
    },
    "tests": {
        "fixture",
        "mock",
        "pytest",
        "spec",
        "test",
        "testing",
    },
    "ui": {
        "button",
        "component",
        "css",
        "dialog",
        "form",
        "html",
        "jsx",
        "menu",
        "modal",
        "page",
        "panel",
        "screen",
        "tsx",
        "ui",
        "view",
        "widget",
    },
}

PATH_CATEGORY_HINTS = {
    ".css": "ui",
    ".html": "ui",
    ".jsx": "ui",
    ".md": "docs",
    ".mdx": "docs",
    ".rst": "docs",
    ".spec.js": "tests",
    ".spec.ts": "tests",
    ".test.js": "tests",
    ".test.ts": "tests",
    ".tsx": "ui",
    ".txt": "docs",
    ".yaml": "config",
    ".yml": "config",
}


@dataclass(frozen=True)
class TaggableDocument:
    id: str
    title: str
    path: str | None = None
    kind: str | None = None
    text: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TaggingResult:
    tags: list[str]
    categories: list[str]
    token_count: int


def tokenize_identifier(value: str) -> list[str]:
    normalized = NON_IDENTIFIER_CHARS.sub(" ", value)
    tokens: list[str] = []
    for chunk in normalized.split():
        chunk = CAMEL_ACRONYM_BOUNDARY.sub(r"\1 \2", chunk)
        chunk = CAMEL_WORD_BOUNDARY.sub(r"\1 \2", chunk)
        tokens.extend(normalize_token(part) for part in chunk.split())
    return [token for token in tokens if token]


def tokenize_text(value: str) -> list[str]:
    return [token for token in tokenize_identifier(value) if token not in STOPWORDS]


def tag_documents(
    documents: list[TaggableDocument],
    *,
    max_tags: int = 8,
    max_categories: int = 4,
) -> dict[str, TaggingResult]:
    if not documents:
        return {}

    token_counts = {document.id: Counter(document_tokens(document)) for document in documents}
    document_frequency = Counter[str]()
    for counts in token_counts.values():
        document_frequency.update(counts.keys())

    document_total = len(documents)
    results: dict[str, TaggingResult] = {}
    for document in documents:
        counts = token_counts[document.id]
        tags = top_tfidf_tags(counts, document_frequency, document_total, max_tags)
        category_candidates = tags + list(counts.keys())
        categories = classify_categories(
            path=document.path,
            kind=document.kind,
            tokens=category_candidates,
            max_categories=max_categories,
        )
        results[document.id] = TaggingResult(
            tags=tags,
            categories=categories,
            token_count=sum(counts.values()),
        )
    return results


def document_tokens(document: TaggableDocument) -> list[str]:
    text_parts = [
        document.title,
        document.path or "",
        document.kind or "",
        metadata_text(document.metadata),
        document.text,
    ]
    tokens = tokenize_text(" ".join(text_parts))
    path_tokens = tokenize_text(document.path or "")
    title_tokens = tokenize_text(document.title)
    return tokens + path_tokens + title_tokens


def top_tfidf_tags(
    counts: Counter[str],
    document_frequency: Counter[str],
    document_total: int,
    max_tags: int,
) -> list[str]:
    if not counts:
        return []
    total_terms = sum(counts.values())
    scored: list[tuple[str, float]] = []
    for token, count in counts.items():
        if len(token) < 2 or token in STOPWORDS:
            continue
        term_frequency = count / total_terms
        inverse_document_frequency = math.log(
            (1 + document_total) / (1 + document_frequency[token])
        )
        score = term_frequency * (inverse_document_frequency + 1)
        scored.append((token, score))
    ranked = sorted(scored, key=lambda item: (-item[1], item[0]))
    return [token for token, _score in ranked[:max_tags]]


def classify_categories(
    *,
    path: str | None,
    kind: str | None,
    tokens: list[str],
    max_categories: int = 4,
) -> list[str]:
    scores = Counter[str]()
    lower_path = (path or "").lower()

    if kind in {"doc_page", "doc_section"}:
        scores["docs"] += 2
    if kind == "config":
        scores["config"] += 2
    if kind == "chunk" and lower_path:
        scores.update(
            classify_categories(
                path=path,
                kind=None,
                tokens=[],
                max_categories=max_categories,
            )
        )

    for suffix, category in PATH_CATEGORY_HINTS.items():
        if lower_path.endswith(suffix):
            scores[category] += 2

    path_parts = tokenize_text(lower_path)
    for token in tokens + path_parts:
        for category, terms in CATEGORY_TERMS.items():
            if token in terms:
                scores[category] += 1

    if "/test" in lower_path or "tests/" in lower_path or "__tests__" in lower_path:
        scores["tests"] += 2
    if "/docs" in lower_path or lower_path.startswith("docs/"):
        scores["docs"] += 2
    if "/components" in lower_path or lower_path.startswith("components/"):
        scores["ui"] += 2

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [category for category, score in ranked[:max_categories] if score > 0]


def metadata_text(metadata: Mapping[str, object]) -> str:
    values: list[str] = []
    for value in metadata.values():
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
        elif isinstance(value, dict):
            values.append(metadata_text(cast(Mapping[str, object], value)))
    return " ".join(values)


def normalize_token(value: str) -> str:
    token = value.lower().strip()
    if len(token) <= 1:
        return ""
    if token.isdigit():
        return ""
    if token in SINGULAR_SUFFIX_EXCEPTIONS:
        return token
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us")):
        return token[:-1]
    return token
