from __future__ import annotations

import html
import json

from guidesync_agent.schemas import GuideSyncRunResult


def render_markdown(result: GuideSyncRunResult) -> str:
    update = result.update
    lines = [
        f"# {result.request.report.title}",
        "",
        f"Run: `{result.run_id}`",
        f"Status: `{result.status}`",
        "",
        "## Summary",
        "",
        update.summary if update else "No update generated.",
        "",
        "## Proposed Update",
        "",
        update.proposed_update_markdown if update else "",
        "",
        "## Evidence Used",
        "",
    ]
    if update:
        for ref in update.evidence_used:
            lines.append(f"- **{ref.source}**: {ref.detail} ({ref.relevance})")
    lines.extend(["", "## Validation Findings", ""])
    if result.findings:
        for finding in result.findings:
            lines.append(f"- `{finding.severity}` / `{finding.check}`: {finding.message}")
    else:
        lines.append("- No validation findings.")
    lines.extend(["", "## Provider", ""])
    if result.provider_metadata:
        lines.append(f"- Provider: `{result.provider_metadata.provider}`")
        lines.append(f"- Model: `{result.provider_metadata.model}`")
        lines.append(f"- Latency: `{result.provider_metadata.latency_ms}ms`")
    return "\n".join(lines).strip() + "\n"


def render_html(result: GuideSyncRunResult) -> str:
    markdown = render_markdown(result)
    escaped = html.escape(markdown)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(result.request.report.title)}</title>
    <style>
      body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin: 40px;
        line-height: 1.5;
        color: #172033;
      }}
      main {{ max-width: 980px; margin: 0 auto; }}
      pre {{
        white-space: pre-wrap;
        background: #f6f8fb;
        border: 1px solid #d8e0ea;
        border-radius: 8px;
        padding: 20px;
      }}
    </style>
  </head>
  <body>
    <main>
      <pre>{escaped}</pre>
    </main>
  </body>
</html>
"""


def write_reports(result: GuideSyncRunResult) -> dict[str, str]:
    output_dir = result.request.report.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    if "md" in result.request.report.formats:
        path = output_dir / "report.md"
        path.write_text(render_markdown(result), encoding="utf-8")
        artifacts["report.md"] = str(path)
    if "html" in result.request.report.formats:
        path = output_dir / "report.html"
        path.write_text(render_html(result), encoding="utf-8")
        artifacts["report.html"] = str(path)
    if "json" in result.request.report.formats:
        path = output_dir / "run.json"
        payload = json.dumps(result.model_dump(mode="json"), indent=2) + "\n"
        path.write_text(payload, encoding="utf-8")
        artifacts["run.json"] = str(path)
    return artifacts
