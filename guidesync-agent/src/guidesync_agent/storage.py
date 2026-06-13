from __future__ import annotations

import json
from pathlib import Path

from guidesync_agent.schemas import GuideSyncRunResult


class FileRunStore:
    def __init__(self, root: Path = Path("outputs/runs")) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, result: GuideSyncRunResult) -> None:
        path = self.root / f"{result.run_id}.json"
        payload = json.dumps(result.model_dump(mode="json"), indent=2) + "\n"
        path.write_text(payload, encoding="utf-8")

    def get(self, run_id: str) -> GuideSyncRunResult | None:
        path = self.root / f"{run_id}.json"
        if not path.exists():
            return None
        return GuideSyncRunResult.model_validate_json(path.read_text(encoding="utf-8"))
