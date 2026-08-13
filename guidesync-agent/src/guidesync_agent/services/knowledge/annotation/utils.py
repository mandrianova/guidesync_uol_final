from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Sequence

from guidesync_agent.services.text_normalization import tokenize_text

from .constants import GENERIC_KEYPHRASE_TERMS, PASCAL_CASE_RE


def clean_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" -_*`#:\n\t")).strip()


def display_keyphrase(value: str) -> str:
    cleaned = clean_phrase(value)
    if not cleaned:
        return ""
    if PASCAL_CASE_RE.search(cleaned):
        return cleaned
    normalized = normalize_phrase(cleaned)
    return normalized or cleaned.lower()


def normalize_phrase(value: str) -> str:
    return " ".join(tokenize_text(value))


def filter_name(value: str) -> str:
    cleaned = clean_phrase(value)
    if not cleaned or len(cleaned) > 120:
        return ""
    normalized = normalize_phrase(cleaned)
    if len(normalized) < 3:
        return ""
    if normalized in GENERIC_KEYPHRASE_TERMS:
        return ""
    return cleaned


def strong_candidate_concept(value: str) -> bool:
    normalized = normalize_phrase(value)
    if len(normalized.split()) >= 2:
        return True
    return bool(PASCAL_CASE_RE.search(value))


def token_overlap_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / math.sqrt(len(left) * len(right))


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return float(numerator / (left_norm * right_norm))


def dedupe(values: Sequence[str]) -> list[str]:
    return unique_strings(values)


def dedupe_display(values: Iterable[str]) -> list[str]:
    return unique_strings(value for value in values if value)


def unique_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = clean_phrase(value)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        result.append(cleaned)
        seen.add(key)
    return result


def stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
