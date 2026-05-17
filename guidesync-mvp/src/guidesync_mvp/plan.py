from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
        file.write("\n")


def mvp_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_output_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    root = mvp_root()
    if path.parts[:2] == ("project", "guidesync-mvp"):
        return root.parent.parent / path
    return root / path


def _normalise_step(index: int, raw_step: dict[str, Any], ui_url: str) -> dict[str, Any]:
    step = dict(raw_step)
    step.setdefault("id", f"step-{index:02d}")
    step.setdefault("action", "screenshot")
    if step["action"] == "navigate" and "target" not in step:
        step["target"] = ui_url
    step.setdefault("screenshot", f"{index:02d}-{step['id']}.png")
    step.setdefault("capture", {"full_page": True})
    return step


def _fallback_steps(task: dict[str, Any]) -> list[dict[str, Any]]:
    ui = task["ui"]
    workflow = task.get("workflow") or {}
    route_hint = workflow.get("route_hint")
    steps: list[dict[str, Any]] = [
        {
            "id": "open-app",
            "action": "navigate",
            "target": ui["url"],
            "expected": "Login page or authenticated application shell is visible.",
            "expected_text": [],
            "screenshot": "01-open-app.png",
            "notes": "Use headed/manual auth only for local debugging. CI should use browser_state or token auth.",
        }
    ]
    if route_hint:
        target = route_hint
        if isinstance(route_hint, str) and route_hint.startswith("/"):
            target = ui["url"].rstrip("/") + route_hint
        steps.append(
            {
                "id": "open-workflow",
                "action": "navigate",
                "target": target,
                "expected": "Target workflow screen is visible.",
                "expected_text": workflow.get("expected_text", []),
                "screenshot": "02-open-workflow.png",
            }
        )
    else:
        steps.append(
            {
                "id": "capture-current-state",
                "action": "screenshot",
                "expected": "Current application state is captured for guide review.",
                "screenshot": "02-current-state.png",
            }
        )
    return steps


def build_plan(task: dict[str, Any]) -> dict[str, Any]:
    ui = task["ui"]
    workflow = task.get("workflow") or {}
    raw_steps = workflow.get("capture_steps") or _fallback_steps(task)
    steps = [_normalise_step(index, step, ui["url"]) for index, step in enumerate(raw_steps, start=1)]
    return {
        "schema_version": 1,
        "run_id": task["task_id"],
        "ui_url": ui["url"],
        "auth": ui.get("auth", {"mode": "none"}),
        "workflow_goal": workflow.get("goal", ""),
        "route_hint": workflow.get("route_hint", ""),
        "steps": steps,
        "fallback_manual_steps": workflow.get("steps_hint", []),
        "documentation": task.get("documentation", {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a reusable GuideSync screenshot plan from a task JSON file.")
    parser.add_argument("--task", required=True, type=Path, help="Path to task JSON.")
    parser.add_argument("--output", type=Path, help="Path to write screenshot-plan.json. Defaults to task.output.root.")
    args = parser.parse_args()

    task = load_json(args.task)
    output_path = args.output or resolve_output_path(Path(task["output"]["root"]) / "screenshot-plan.json")
    write_json(output_path, build_plan(task))
    print(output_path)


if __name__ == "__main__":
    main()
