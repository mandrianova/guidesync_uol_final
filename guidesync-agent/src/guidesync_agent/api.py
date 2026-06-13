from __future__ import annotations

import argparse

import uvicorn
from fastapi import FastAPI, HTTPException

from guidesync_agent.agent import run_guidesync
from guidesync_agent.schemas import GuideSyncRunRequest, GuideSyncRunResult
from guidesync_agent.storage import FileRunStore

app = FastAPI(title="GuideSync Agent", version="0.1.0")
store = FileRunStore()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "guidesync-agent"}


@app.post("/runs")
async def create_run(request: GuideSyncRunRequest) -> GuideSyncRunResult:
    result = await run_guidesync(request)
    store.save(result)
    return result


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> GuideSyncRunResult:
    result = store.get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the GuideSync Agent FastAPI app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8770, type=int)
    args = parser.parse_args()
    uvicorn.run("guidesync_agent.api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
