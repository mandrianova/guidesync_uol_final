from __future__ import annotations

import html
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import boto3

from guidesync_agent.config import ArtifactStorageConfig, artifact_storage_config
from guidesync_agent.schemas import (
    GuideSyncRunResult,
    LLMTranscriptSummary,
    RunTokenUsageSummary,
    TokenUsageSummaryItem,
)
from guidesync_agent.services.markdown_document import render_markdown_html
from guidesync_agent.storage import create_llm_transcript_store, create_model_usage_store


@dataclass(frozen=True)
class ArtifactContent:
    body: bytes
    content_type: str


def render_markdown(result: GuideSyncRunResult) -> str:
    update = result.update
    token_summary = token_usage_summary_for_run(result.run_id)
    transcripts = transcript_summaries_for_run(result.run_id)
    lines = [
        f"# {result.request.report.title}",
        "",
        f"Run: `{result.run_id}`",
        f"Status: `{result.status}`",
        "",
        "## Summary",
        "",
        update.summary if update else "No release notes generated.",
        "",
        "## Release Notes Draft",
        "",
        update.proposed_update_markdown if update else "",
        "",
        "## Evidence Used",
        "",
    ]
    if update:
        for ref in update.evidence_used:
            lines.append(f"- **{ref.source}**: {ref.detail} ({ref.relevance})")
    if update and update.documentation_edit:
        edit = update.documentation_edit
        lines.extend(["", "## Documentation Edit", ""])
        lines.append(f"- Repository: `{edit.repository_id}`")
        lines.append(f"- Target: `{edit.target_path}`")
        lines.append(f"- Commit: `{edit.commit_sha or 'patch only'}`")
        if edit.knowledge_index_run_id:
            lines.append(f"- Knowledge index run: `{edit.knowledge_index_run_id}`")
    if result.evidence.browser_screenshots:
        lines.extend(["", "## Screenshots", ""])
        for screenshot in result.evidence.browser_screenshots:
            lines.append(f"- **{screenshot.scenario}**: {screenshot.url}")
            lines.append(f"  - Path: `{screenshot.path}`")
            if screenshot.title:
                lines.append(f"  - Title: {screenshot.title}")
            if screenshot.image_hash:
                lines.append(f"  - Hash: `{screenshot.image_hash}`")
            if screenshot.validation_status:
                lines.append(f"  - Validation: `{screenshot.validation_status}`")
            if screenshot.validation_reasons:
                lines.append(f"  - Validation reasons: {', '.join(screenshot.validation_reasons)}")
            if screenshot.attempts > 1:
                lines.append(f"  - Attempts: {screenshot.attempts}")
            if screenshot.missing_text:
                lines.append(f"  - Missing text: {', '.join(screenshot.missing_text)}")
    if result.artifacts:
        lines.extend(["", "## Artifacts", ""])
        for name, uri in sorted(result.artifacts.items()):
            lines.append(f"- `{name}`: `{uri}`")
    if token_summary is not None:
        lines.extend(token_usage_markdown_lines(token_summary))
    if transcripts:
        lines.extend(transcript_markdown_lines(transcripts))
    lines.extend(["", "## Validation Findings", ""])
    if result.findings:
        for finding in result.findings:
            lines.append(f"- `{finding.severity}` / `{finding.check}`: {finding.message}")
            if finding.evidence_refs:
                lines.append(f"  - Evidence refs: {', '.join(finding.evidence_refs)}")
            if finding.artifact_refs:
                lines.append(f"  - Artifact refs: {', '.join(finding.artifact_refs)}")
    else:
        lines.append("- No validation findings.")
    lines.extend(["", "## Provider", ""])
    if result.provider_metadata:
        lines.append(f"- Provider: `{result.provider_metadata.provider}`")
        lines.append(f"- Model: `{result.provider_metadata.model}`")
        lines.append(f"- Latency: `{result.provider_metadata.latency_ms}ms`")
    effective_model = result.request.effective_model_configuration
    lines.extend(["", "## Run Configuration", ""])
    lines.append(f"- Screenshot policy: `{result.request.screenshot_policy.value}`")
    if result.request.task_interface_url:
        lines.append(f"- Task interface URL: {result.request.task_interface_url}")
    if result.request.project_profile_snapshot_id:
        lines.append(f"- Project profile: `{result.request.project_profile_snapshot_id}`")
    if effective_model:
        lines.append(f"- Effective provider: `{effective_model.provider.value}`")
        lines.append(f"- Effective model: `{effective_model.model}`")
        lines.append(f"- Effective timeout: `{effective_model.timeout_seconds}s`")
        lines.append(
            f"- Maximum concurrent agents: `{effective_model.max_concurrent_agents}`"
        )
        if effective_model.thinking is not None:
            lines.append(f"- Effective thinking: `{effective_model.thinking}`")
    return "\n".join(lines).strip() + "\n"


def render_html(result: GuideSyncRunResult) -> str:
    markdown = render_markdown(result)
    rendered = render_markdown_html(markdown)
    update = result.update
    provider = result.provider_metadata
    title = update.title if update else result.request.report.title
    summary = update.summary if update else "No release notes generated."
    provider_label = (
        f"{html.escape(provider.provider)} / {html.escape(provider.model)}"
        if provider
        else "Provider not recorded"
    )
    latency_label = f"{provider.latency_ms}ms" if provider else "n/a"
    evidence_count = len(result.evidence.commits)
    artifact_count = len(result.artifacts)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(result.request.report.title)}</title>
    <style>
      :root {{
        --ink: #142033;
        --muted: #5b6881;
        --line: #d7dee9;
        --paper: #fbfcfd;
        --accent: #0f766e;
        --accent-soft: #e8f7f4;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        background:
          linear-gradient(#eef2f6 1px, transparent 1px),
          linear-gradient(90deg, #eef2f6 1px, transparent 1px),
          #faf9f5;
        background-size: 28px 28px;
        color: var(--ink);
        font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        line-height: 1.55;
        margin: 0;
      }}
      .page {{
        margin: 0 auto;
        max-width: 1040px;
        padding: 42px 28px 56px;
      }}
      .report-shell {{
        background: rgba(255, 255, 255, 0.94);
        border: 2px solid var(--ink);
        box-shadow: 6px 6px 0 rgba(20, 32, 51, 0.18);
      }}
      .hero {{
        border-bottom: 2px solid var(--ink);
        display: grid;
        gap: 18px;
        grid-template-columns: 1fr auto;
        padding: 28px;
      }}
      .eyebrow {{
        color: var(--accent);
        font-size: 0.78rem;
        font-weight: 900;
        letter-spacing: 0;
        margin: 0 0 8px;
        text-transform: uppercase;
      }}
      h1, h2, h3 {{ line-height: 1.15; margin: 0; }}
      h1 {{ font-size: clamp(2rem, 6vw, 3.2rem); max-width: 860px; }}
      .summary {{
        color: var(--muted);
        font-size: 1.05rem;
        margin: 14px 0 0;
        max-width: 780px;
      }}
      .actions {{
        align-items: flex-end;
        display: flex;
        gap: 10px;
      }}
      button {{
        background: var(--accent);
        border: 2px solid var(--ink);
        color: white;
        cursor: pointer;
        font: inherit;
        font-weight: 900;
        padding: 10px 14px;
      }}
      .meta-grid {{
        border-bottom: 1px solid var(--line);
        display: grid;
        grid-template-columns: repeat(4, 1fr);
      }}
      .meta-item {{
        border-right: 1px solid var(--line);
        padding: 16px 18px;
      }}
      .meta-item:last-child {{ border-right: 0; }}
      .meta-item strong {{
        display: block;
        font-size: 0.76rem;
        margin-bottom: 5px;
        text-transform: uppercase;
      }}
      .meta-item span {{
        color: var(--muted);
        overflow-wrap: anywhere;
      }}
      .content {{
        display: grid;
        gap: 22px;
        padding: 28px;
      }}
      .document {{
        background: var(--paper);
        border: 1px solid var(--line);
        display: grid;
        gap: 14px;
        padding: 24px;
      }}
      .document h1 {{
        border-bottom: 2px solid var(--ink);
        font-size: 1.8rem;
        padding-bottom: 12px;
      }}
      .document h2 {{
        font-size: 1.25rem;
        margin-top: 12px;
      }}
      .document h3 {{ font-size: 1.05rem; }}
      .document p, .document ul {{ margin: 0; }}
      .document ul {{ padding-left: 24px; }}
      .document li {{ margin: 8px 0; }}
      code {{
        background: #f6f8fb;
        border: 1px solid #d8e0ea;
        border-radius: 4px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 0.9em;
        padding: 2px 5px;
      }}
      a {{ color: var(--accent); font-weight: 800; }}
      .status {{
        background: var(--accent-soft);
        border: 1px solid #8dd8ca;
        border-radius: 999px;
        color: var(--accent);
        display: inline-flex;
        font-weight: 900;
        padding: 5px 10px;
      }}
      @media print {{
        body {{ background: white; }}
        .page {{ max-width: none; padding: 0; }}
        .report-shell {{ border: 0; box-shadow: none; }}
        .hero {{ padding: 0 0 16px; }}
        .actions {{ display: none; }}
        .content {{ padding: 18px 0 0; }}
        .document {{ border: 0; padding: 0; }}
        a {{ color: inherit; text-decoration: none; }}
      }}
      @media (max-width: 760px) {{
        .hero {{ grid-template-columns: 1fr; }}
        .actions {{ align-items: stretch; }}
        .meta-grid {{ grid-template-columns: 1fr; }}
        .meta-item {{ border-right: 0; border-bottom: 1px solid var(--line); }}
      }}
    </style>
  </head>
  <body>
    <main class="page">
      <article class="report-shell">
        <header class="hero">
          <div>
            <p class="eyebrow">GuideSync release notes report</p>
            <h1>{html.escape(title)}</h1>
            <p class="summary">{html.escape(summary)}</p>
          </div>
          <div class="actions">
            <button type="button" onclick="window.print()">Save PDF</button>
          </div>
        </header>
        <section class="meta-grid" aria-label="Run metadata">
          <div class="meta-item">
            <strong>Status</strong>
            <span class="status">{html.escape(result.status)}</span>
          </div>
          <div class="meta-item">
            <strong>Run</strong>
            <span>{html.escape(result.run_id)}</span>
          </div>
          <div class="meta-item">
            <strong>Provider</strong>
            <span>{provider_label}<br />{html.escape(latency_label)}</span>
          </div>
          <div class="meta-item">
            <strong>Evidence</strong>
            <span>{evidence_count} commits<br />{artifact_count} artifacts</span>
          </div>
        </section>
        <section class="content">
          <div class="document">
            {rendered}
          </div>
        </section>
      </article>
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


def token_usage_summary_for_run(run_id: str) -> RunTokenUsageSummary | None:
    try:
        summary = create_model_usage_store().summarize_run(run_id)
    except Exception:  # noqa: BLE001 - report rendering should not fail on optional summary
        return None
    return summary if summary.calls else None


def token_usage_markdown_lines(summary: RunTokenUsageSummary) -> list[str]:
    lines = [
        "",
        "## Token Usage",
        "",
        f"- Total tokens: `{summary.total_tokens}`",
        f"- Model calls: `{summary.calls}`",
        f"- Estimated tokens: `{summary.estimated_tokens}`",
    ]
    lines.extend(token_usage_items("By role", summary.by_role))
    lines.extend(token_usage_items("By provider", summary.by_provider))
    lines.extend(token_usage_items("By model", summary.by_model))
    if summary.by_workflow_task:
        lines.extend(token_usage_items("By workflow task", summary.by_workflow_task))
    if summary.warnings:
        lines.append("- Warnings:")
        lines.extend(f"  - {warning}" for warning in summary.warnings[:10])
    return lines


def token_usage_items(
    label: str,
    items: list[TokenUsageSummaryItem],
) -> list[str]:
    if not items:
        return []
    lines = [f"- {label}:"]
    lines.extend(
        f"  - `{item.key}`: `{item.total_tokens}` tokens across `{item.calls}` calls"
        for item in items
    )
    return lines


def transcript_summaries_for_run(run_id: str) -> list[LLMTranscriptSummary]:
    try:
        return create_llm_transcript_store().list_for_run(run_id)
    except Exception:  # noqa: BLE001 - report rendering should not fail on optional refs
        return []


def transcript_markdown_lines(transcripts: list[LLMTranscriptSummary]) -> list[str]:
    lines = ["", "## LLM Transcripts", ""]
    for transcript in transcripts:
        lines.append(
            f"- `{transcript.id}`: `{transcript.model_role.value}` "
            f"`{transcript.provider.value}/{transcript.model}` "
            f"messages `{transcript.message_count}`, tools `{transcript.tool_call_count}`"
        )
        if transcript.workflow_task_id:
            lines.append(f"  - Workflow task: `{transcript.workflow_task_id}`")
        if transcript.transcript_artifact_ref:
            lines.append(f"  - Artifact: `{transcript.transcript_artifact_ref}`")
    return lines


def run_json_payload(result: GuideSyncRunResult, artifacts: dict[str, str]) -> str:
    payload = result.model_copy(update={"artifacts": artifacts}).model_dump(mode="json")
    token_summary = token_usage_summary_for_run(result.run_id)
    if token_summary is not None:
        payload["token_usage_summary"] = token_summary.model_dump(mode="json")
    transcripts = transcript_summaries_for_run(result.run_id)
    if transcripts:
        payload["llm_transcripts"] = [item.model_dump(mode="json") for item in transcripts]
    return json.dumps(payload, indent=2) + "\n"


def write_file_reports(result: GuideSyncRunResult, payloads: dict[str, str]) -> dict[str, str]:
    output_dir = result.request.report.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    for filename, payload in payloads.items():
        path = output_dir / filename
        path.write_text(payload, encoding="utf-8")
        artifacts[filename] = str(path)
    return artifacts


def s3_artifact_uri(config: ArtifactStorageConfig, key: str) -> str:
    if not config.bucket:
        raise RuntimeError("GUIDESYNC_S3_BUCKET is required when artifact storage is s3.")
    return (
        f"{config.public_base_url}/{key}"
        if config.public_base_url
        else f"s3://{config.bucket}/{key}"
    )


def write_s3_reports(
    result: GuideSyncRunResult,
    payloads: dict[str, str],
    config: ArtifactStorageConfig,
) -> dict[str, str]:
    if not config.bucket:
        raise RuntimeError("GUIDESYNC_S3_BUCKET is required when artifact storage is s3.")
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
        artifacts[filename] = s3_artifact_uri(config, key)
    return artifacts


def write_s3_existing_artifacts(
    result: GuideSyncRunResult,
    artifacts: dict[str, str],
    config: ArtifactStorageConfig,
) -> dict[str, str]:
    if not config.bucket:
        raise RuntimeError("GUIDESYNC_S3_BUCKET is required when artifact storage is s3.")
    client = boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
    )
    uploaded: dict[str, str] = {}
    for filename, uri in artifacts.items():
        parsed = urlparse(uri)
        if parsed.scheme:
            continue
        path = Path(uri)
        if not path.is_file():
            continue
        key = f"{config.prefix}/{result.run_id}/{filename}"
        client.put_object(
            Bucket=config.bucket,
            Key=key,
            Body=path.read_bytes(),
            ContentType=content_type_for_name(filename),
        )
        uploaded[filename] = s3_artifact_uri(config, key)
    return uploaded


def write_reports(result: GuideSyncRunResult) -> dict[str, str]:
    artifacts = dict(result.artifacts)
    config = artifact_storage_config()
    if config.backend == "s3":
        artifacts.update(write_s3_existing_artifacts(result, artifacts, config))
        result_with_artifacts = result.model_copy(update={"artifacts": artifacts})
        artifacts.update(
            write_s3_reports(
                result_with_artifacts,
                artifact_payloads(result_with_artifacts),
                config,
            )
        )
        if "json" in result.request.report.formats:
            json_payload = run_json_payload(result, artifacts)
            artifacts.update(write_s3_reports(result, {"run.json": json_payload}, config))
        return artifacts

    payloads = artifact_payloads(result)
    artifacts.update(write_file_reports(result, payloads))
    if "json" in result.request.report.formats:
        json_payload = run_json_payload(result, artifacts)
        artifacts.update(write_file_reports(result, {"run.json": json_payload}))
    return artifacts


def read_artifact(uri: str) -> ArtifactContent:
    parsed = urlparse(uri)
    if parsed.scheme == "s3":
        return read_s3_artifact(parsed.netloc, parsed.path.lstrip("/"))
    if parsed.scheme in {"http", "https"}:
        raise ValueError("Remote public artifact URLs should be opened directly.")
    return read_file_artifact(Path(uri))


def read_s3_artifact(bucket: str, key: str) -> ArtifactContent:
    config = artifact_storage_config()
    client = boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
    )
    response = client.get_object(Bucket=bucket, Key=key)
    content_type = response.get("ContentType") or content_type_for_name(key)
    return ArtifactContent(
        body=response["Body"].read(),
        content_type=content_type,
    )


def read_file_artifact(path: Path) -> ArtifactContent:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    return ArtifactContent(
        body=path.read_bytes(),
        content_type=content_type_for_name(path.name),
    )


def content_type_for_name(name: str) -> str:
    if name.endswith(".md"):
        return "text/markdown; charset=utf-8"
    if name.endswith(".html"):
        return "text/html; charset=utf-8"
    if name.endswith(".json"):
        return "application/json; charset=utf-8"
    return mimetypes.guess_type(name)[0] or "application/octet-stream"
