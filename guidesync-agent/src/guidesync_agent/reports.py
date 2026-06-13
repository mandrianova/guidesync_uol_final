from __future__ import annotations

import html
import json

from guidesync_agent.config import ArtifactStorageConfig, artifact_storage_config
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


def artifact_payloads(result: GuideSyncRunResult) -> dict[str, str]:
    payloads: dict[str, str] = {}
    if "md" in result.request.report.formats:
        payloads["report.md"] = render_markdown(result)
    if "html" in result.request.report.formats:
        payloads["report.html"] = render_html(result)
    return payloads


def write_file_reports(result: GuideSyncRunResult, payloads: dict[str, str]) -> dict[str, str]:
    output_dir = result.request.report.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for filename, payload in payloads.items():
        path = output_dir / filename
        path.write_text(payload, encoding="utf-8")
        artifacts[filename] = str(path)
    return artifacts


def write_s3_reports(
    result: GuideSyncRunResult,
    payloads: dict[str, str],
    config: ArtifactStorageConfig,
) -> dict[str, str]:
    if not config.bucket:
        raise RuntimeError("GUIDESYNC_S3_BUCKET is required when artifact storage is s3.")
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for S3 artifact storage. Run `uv sync`.") from exc

    client = boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
    )
    artifacts: dict[str, str] = {}
    for filename, payload in payloads.items():
        key = f"{config.prefix}/{result.run_id}/{filename}"
        content_type = {
            "report.html": "text/html; charset=utf-8",
            "report.md": "text/markdown; charset=utf-8",
            "run.json": "application/json; charset=utf-8",
        }.get(filename, "text/plain; charset=utf-8")
        client.put_object(
            Bucket=config.bucket,
            Key=key,
            Body=payload.encode("utf-8"),
            ContentType=content_type,
        )
        artifacts[filename] = (
            f"{config.public_base_url}/{key}"
            if config.public_base_url
            else f"s3://{config.bucket}/{key}"
        )
    return artifacts


def write_reports(result: GuideSyncRunResult) -> dict[str, str]:
    payloads = artifact_payloads(result)
    config = artifact_storage_config()
    if config.backend == "s3":
        artifacts = write_s3_reports(result, payloads, config)
        if "json" in result.request.report.formats:
            json_payload = (
                json.dumps(
                    result.model_copy(update={"artifacts": artifacts}).model_dump(mode="json"),
                    indent=2,
                )
                + "\n"
            )
            artifacts.update(write_s3_reports(result, {"run.json": json_payload}, config))
        return artifacts

    artifacts = write_file_reports(result, payloads)
    if "json" in result.request.report.formats:
        json_payload = (
            json.dumps(
                result.model_copy(update={"artifacts": artifacts}).model_dump(mode="json"),
                indent=2,
            )
            + "\n"
        )
        artifacts.update(write_file_reports(result, {"run.json": json_payload}))
    return artifacts
