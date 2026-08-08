from __future__ import annotations

import re

DEFAULT_SPACY_MODEL = "en_core_web_sm"
NLP_METHOD_VERSION = "knowledge-annotation-nlp-v1"
DETERMINISTIC_ANALYZER_ID = "deterministic-analyzer-v1"
DETERMINISTIC_SEMANTIC_ID = "deterministic-semantic-v1"
MAX_SEMANTIC_KEYPHRASE_CANDIDATES = 48
BOOTSTRAP_HINTS = {
    "billing",
    "auth",
    "user-management",
    "workspace",
    "settings",
    "api",
    "ui-workflow",
    "release-notes",
    "docs",
}
WORKFLOW_VERBS = {
    "add",
    "build",
    "configure",
    "connect",
    "create",
    "generate",
    "index",
    "manage",
    "publish",
    "review",
    "run",
    "search",
    "setup",
    "update",
}
GENERIC_KEYPHRASE_TERMS = {
    "document",
    "documentation",
    "guide",
    "section",
    "source",
    "text",
}

PASCAL_CASE_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:[A-Z][a-z0-9]+)[A-Za-z0-9]*\b")
TITLE_LABEL_RE = re.compile(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){1,4}\b")
QUOTED_LABEL_RE = re.compile(r"[\"']([^\"'\n]{2,80})[\"']")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
