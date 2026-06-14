from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from guidesync_agent.app_logging import configure_logging
from guidesync_agent.pipeline import run_guidesync, save_run_state
from guidesync_agent.schemas import GuideSyncRunRequest

__all__ = ["load_request", "main", "run_guidesync", "save_run_state"]


def load_request(path: Path) -> GuideSyncRunRequest:
    return GuideSyncRunRequest.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Run a GuideSync release notes task.")
    parser.add_argument("request", type=Path, help="Path to a GuideSync run request JSON file.")
    args = parser.parse_args()
    result = asyncio.run(run_guidesync(load_request(args.request)))
    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
