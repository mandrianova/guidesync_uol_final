from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from guidesync_agent.schemas import EvidenceBundle


def screenshot_evidence_artifacts(
    output_dir: Path,
    evidence: EvidenceBundle,
) -> dict[str, str]:
    if not evidence.browser_screenshots:
        return {}
    screenshot_dir = output_dir / "screenshots"
    artifacts = {
        "screenshot-evidence.json": write_json(
            screenshot_dir / "screenshot-evidence.json",
            {
                "screenshots": [
                    screenshot.model_dump(mode="json")
                    for screenshot in evidence.browser_screenshots
                ]
            },
        )
    }
    for screenshot in evidence.browser_screenshots:
        if screenshot.raw_path:
            artifacts[Path(screenshot.raw_path).name] = screenshot.raw_path
        if screenshot.publication_approved and screenshot.prepared_artifact_name:
            artifacts[screenshot.prepared_artifact_name] = screenshot.path
    return artifacts


def write_json(path: Path, payload: Mapping[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return str(path)
