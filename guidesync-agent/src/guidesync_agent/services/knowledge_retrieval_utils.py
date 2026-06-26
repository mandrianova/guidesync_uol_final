from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from guidesync_agent.knowledge_tagging import tokenize_text

TEXT_METADATA_KEYS = ("search_terms",)
TAXONOMY_METADATA_KEYS = ("categories", "concepts")
KEYPHRASE_METADATA_KEYS = ("tags", "keyphrases")
NAME_METADATA_KEYS = ("extracted_names",)
REVIEW_METADATA_KEY = "needs_taxonomy_review"
POSTGRES_FULL_TEXT_METADATA_KEY = "postgres_full_text_score"


def score_knowledge_text(query: str, text: str) -> float:
    query_text = query.strip()
    query_lower = query_text.lower()
    target_lower = text.lower()
    terms = tokenize_text(query_text)
    if not terms:
        return 0.0
    target_terms = Counter(tokenize_text(text))
    score = 0.0
    if query_lower in target_lower:
        score += 4.0
    for term in terms:
        score += min(target_terms[term], 3)
    return score


def metadata_text(metadata: dict[str, object]) -> str:
    values: list[str] = []
    for key in (*TEXT_METADATA_KEYS, *TAXONOMY_METADATA_KEYS, *KEYPHRASE_METADATA_KEYS):
        values.extend(list_metadata(metadata, key))
    return " ".join(values)


def embedding_signal(metadata: dict[str, object]) -> tuple[float, str | None]:
    model_id = string_metadata(metadata, "embedding_model_id")
    value = metadata.get("embedding_similarity", metadata.get("embedding_score"))
    if isinstance(value, (int, float)):
        return max(float(value), 0.0), model_id
    return 0.0, model_id


def postgres_full_text_signal(metadata: dict[str, object]) -> float:
    value = metadata.get(POSTGRES_FULL_TEXT_METADATA_KEY)
    if isinstance(value, (int, float)):
        return max(float(value), 0.0) * 10.0
    return 0.0


def list_metadata(metadata: dict[str, object], key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def string_metadata(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def normalized_set(values: Iterable[str]) -> set[str]:
    return {normalized for value in values if (normalized := normalize_phrase(value))}


def normalize_phrase(value: str) -> str:
    return " ".join(tokenize_text(value))


def token_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(right), 1)


def unique_sorted(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        result.append(value)
        seen.add(key)
    return sorted(result, key=str.lower)


def trim_excerpt(text: str, query: str, limit: int = 320) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    index = compact.lower().find(query.lower().strip())
    if index < 0:
        return compact[: limit - 3] + "..."
    start = max(index - 80, 0)
    prefix = "..." if start > 0 else ""
    body_limit = limit - len(prefix) - 3
    end = min(start + body_limit, len(compact))
    suffix = "..." if end < len(compact) else ""
    if not suffix:
        body_limit = limit - len(prefix)
        end = min(start + body_limit, len(compact))
    return f"{prefix}{compact[start:end]}{suffix}"
