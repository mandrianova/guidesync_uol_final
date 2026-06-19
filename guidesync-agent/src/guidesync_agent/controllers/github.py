from __future__ import annotations

from guidesync_agent.evidence import list_github_branches


def list_branches(url: str) -> dict[str, list[dict[str, str | None]] | str | None]:
    branches, warning = list_github_branches(url)
    return {"branches": branches, "warning": warning}

