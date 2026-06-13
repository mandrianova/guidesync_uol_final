from __future__ import annotations

import argparse
import asyncio
import time

from guidesync_agent.agent import run_guidesync, save_run_state
from guidesync_agent.schemas import GuideSyncRunResult, ValidationFinding
from guidesync_agent.storage import create_run_store, initialize_storage


async def run_worker_once() -> GuideSyncRunResult | None:
    store = create_run_store()
    claimed = store.claim_next_queued_run()
    if claimed is None:
        return None
    try:
        return await run_guidesync(claimed.request)
    except Exception as exc:  # noqa: BLE001 - worker must persist pipeline failure
        return save_run_state(
            claimed.request,
            "failed",
            [ValidationFinding(severity="error", check="worker", message=str(exc))],
        )


def run_worker_loop(interval_seconds: float) -> None:
    initialize_storage()
    while True:
        result = asyncio.run(run_worker_once())
        if result is None:
            time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GuideSync background worker.")
    parser.add_argument("--interval", default=5.0, type=float, help="Polling interval in seconds.")
    parser.add_argument("--once", action="store_true", help="Process at most one queued run.")
    args = parser.parse_args()
    initialize_storage()
    if args.once:
        asyncio.run(run_worker_once())
        return
    run_worker_loop(args.interval)


if __name__ == "__main__":
    main()
