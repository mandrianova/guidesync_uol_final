from __future__ import annotations

import re

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
    "function",
    "has",
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


def normalize_token(value: str) -> str:
    token = value.lower().strip()
    normalized = token
    if len(token) <= 1 or token.isdigit():
        normalized = ""
    elif token not in SINGULAR_SUFFIX_EXCEPTIONS:
        if len(token) > 4 and token.endswith("ies"):
            normalized = f"{token[:-3]}y"
        elif len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us")):
            normalized = token[:-1]
    return normalized
