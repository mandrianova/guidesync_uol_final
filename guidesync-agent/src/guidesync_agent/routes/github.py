from __future__ import annotations

from fastapi import APIRouter, Query

from guidesync_agent.controllers import github

router = APIRouter()


@router.get("/github/branches")
async def github_branches(
    url: str = Query(...),
) -> dict[str, list[dict[str, str | None]] | str | None]:
    return github.list_branches(url)

