from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def read_text_if_exists(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def mvp_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_input_path(path: Path | None) -> Path | None:
    if path is None or path.exists() or path.is_absolute():
        return path
    root = mvp_root()
    if path.parts[:2] == ("project", "guidesync-mvp"):
        workspace_path = root.parent.parent / path
        if workspace_path.exists():
            return workspace_path
    return root / path


def compact_text(text: str, limit: int = 900) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)[:limit]


def build_guide(capture: dict[str, Any], existing_guide: str, title: str) -> str:
    ok_steps = [step for step in capture.get("steps", []) if step.get("status") == "ok"]
    failed_steps = [step for step in capture.get("steps", []) if step.get("status") != "ok"]
    lines: list[str] = [
        f"# {title}",
        "",
        "Status: draft generated from a reusable GuideSync Playwright capture.",
        "",
        "## Source Evidence",
        "",
        f"- Run id: `{capture.get('run_id', '')}`",
        f"- Captured at: `{capture.get('captured_at', '')}`",
        f"- Steps captured: {len(ok_steps)}",
    ]
    if failed_steps:
        lines.append(f"- Steps needing review: {len(failed_steps)}")
    lines.extend(["", "## Workflow Draft", ""])

    for index, step in enumerate(capture.get("steps", []), start=1):
        evidence = step.get("evidence") or {}
        expected = step.get("expected") or "Review this UI state."
        lines.extend(
            [
                f"### Step {index}: {step.get('id', f'step-{index:02d}')}",
                "",
                expected,
                "",
                f"- URL: `{evidence.get('url', '')}`",
                f"- Screenshot: `{step.get('screenshot') or step.get('diagnostic_screenshot', '')}`",
            ]
        )
        matched = step.get("validation", {}).get("matched_text") or []
        missing = step.get("validation", {}).get("missing_text") or []
        if matched:
            lines.append(f"- Matched expected text: {', '.join(f'`{text}`' for text in matched)}")
        if missing:
            lines.append(f"- Missing expected text: {', '.join(f'`{text}`' for text in missing)}")
        visible = compact_text(evidence.get("visible_text", ""))
        if visible:
            lines.extend(["", "Observed UI text excerpt:", "", "```text", visible, "```"])
        lines.append("")

    if existing_guide:
        lines.extend(
            [
                "## Existing Guide Delta",
                "",
                "The previous guide should be reviewed against the captured UI states above. Existing guide excerpt:",
                "",
                "```markdown",
                existing_guide[:1800],
                "```",
                "",
            ]
        )

    if failed_steps:
        lines.extend(["## Review Blockers", ""])
        for step in failed_steps:
            lines.append(f"- `{step.get('id')}` failed: {step.get('error', 'unknown error')}")
        lines.append("")

    lines.extend(
        [
            "## Human Review Checklist",
            "",
            "- Confirm screenshots do not expose private workspace data before publishing.",
            "- Replace any inferred steps with product-approved wording.",
            "- Re-run the same task in CI with stored auth state or token auth before treating this as regression evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a markdown guide draft from GuideSync capture evidence.")
    parser.add_argument("--capture", required=True, type=Path, help="Path to browser-capture.json.")
    parser.add_argument("--output", required=True, type=Path, help="Path to write guide markdown.")
    parser.add_argument("--existing-guide", type=Path, help="Optional stale/existing guide to compare against.")
    parser.add_argument("--title", default="GuideSync Generated Guide", help="Guide title.")
    args = parser.parse_args()

    capture = load_json(args.capture)
    existing = read_text_if_exists(resolve_input_path(args.existing_guide))
    write_text(args.output, build_guide(capture, existing, args.title))
    print(args.output)


if __name__ == "__main__":
    main()
