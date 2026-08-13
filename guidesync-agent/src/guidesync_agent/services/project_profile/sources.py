from __future__ import annotations

import re
from pathlib import Path

PROFILE_SKIP_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "outputs",
    "var",
}
PROFILE_SECRET_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_dsa",
    "known_hosts",
}
PROFILE_SECRET_RE = re.compile(
    r"(^|[./_-])(secret|credentials?|private[-_]?key|api[-_]?key|token|password)([./_-]|$)",
    re.IGNORECASE,
)


def normalized_profile_path(path: str | None) -> str:
    if path is None:
        return "docs/"
    value = path.strip().lstrip("/")
    return value or "."


def is_likely_secret_path(path: Path) -> bool:
    name = path.name.lower()
    return name in PROFILE_SECRET_NAMES or bool(PROFILE_SECRET_RE.search(path.as_posix()))
