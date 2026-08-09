from __future__ import annotations

import hashlib


def stable_id(prefix: str, *parts: str) -> str:
    normalized = "\n".join(part.strip().casefold() for part in parts if part.strip())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"
