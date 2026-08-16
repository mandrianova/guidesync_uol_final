from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from guidesync_agent.config import ArtifactStorageConfig, artifact_storage_config
from guidesync_agent.schemas import (
    BrowserScreenshotEvidence,
    GuideSyncRunResult,
    LLMTranscriptSummary,
    RunTokenUsageSummary,
    TokenUsageSummaryItem,
)
from guidesync_agent.services.reports.publication import build_publication_report
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
    append_evidence_lines(lines, result)
    append_documentation_edit_lines(lines, result)
    append_screenshot_lines(lines, result)
    append_artifact_lines(lines, result)
    if token_summary is not None:
        lines.extend(token_usage_markdown_lines(token_summary))
    if transcripts:
        lines.extend(transcript_markdown_lines(transcripts))
    append_validation_lines(lines, result)
    append_provider_lines(lines, result)
    append_run_configuration_lines(lines, result)
    return "\n".join(lines).strip() + "\n"


def append_evidence_lines(lines: list[str], result: GuideSyncRunResult) -> None:
    update = result.update
    if update:
        for ref in update.evidence_used:
            lines.append(f"- **{ref.source}**: {ref.detail} ({ref.relevance})")


def append_documentation_edit_lines(lines: list[str], result: GuideSyncRunResult) -> None:
    update = result.update
    if update and update.documentation_edit:
        edit = update.documentation_edit
        lines.extend(["", "## Documentation Edit", ""])
        lines.append(f"- Repository: `{edit.repository_id}`")
        lines.append(f"- Target: `{edit.target_path}`")
        lines.append(f"- Commit: `{edit.commit_sha or 'patch only'}`")
        if edit.knowledge_index_run_id:
            lines.append(f"- Knowledge index run: `{edit.knowledge_index_run_id}`")


def append_screenshot_lines(lines: list[str], result: GuideSyncRunResult) -> None:
    if result.evidence.browser_screenshots:
        lines.extend(["", "## Screenshots", ""])
        for screenshot in result.evidence.browser_screenshots:
            lines.extend(screenshot_markdown_lines(screenshot))


def screenshot_markdown_lines(screenshot: BrowserScreenshotEvidence) -> list[str]:
    lines = [
        f"- **{screenshot.scenario}**: {screenshot.url}",
        f"  - Path: `{screenshot.path}`",
    ]
    optional_values = (
        (screenshot.title, "Title", screenshot.title),
        (screenshot.image_hash, "Hash", f"`{screenshot.image_hash}`"),
        (
            screenshot.validation_status,
            "Validation",
            f"`{screenshot.validation_status}`",
        ),
        (
            screenshot.validation_reasons,
            "Validation reasons",
            ", ".join(screenshot.validation_reasons),
        ),
        (screenshot.attempt > 1, "Attempt", screenshot.attempt),
        (
            screenshot.retry_of_capture_id,
            "Retry of capture",
            f"`{screenshot.retry_of_capture_id}`",
        ),
        (
            screenshot.review_verdict,
            "Review verdict",
            f"`{screenshot.review_verdict}`",
        ),
        (screenshot.missing_text, "Missing text", ", ".join(screenshot.missing_text)),
    )
    lines.extend(f"  - {label}: {value}" for present, label, value in optional_values if present)
    return lines


def append_artifact_lines(lines: list[str], result: GuideSyncRunResult) -> None:
    if result.artifacts:
        lines.extend(["", "## Artifacts", ""])
        for name, uri in sorted(result.artifacts.items()):
            lines.append(f"- `{name}`: `{uri}`")


def append_validation_lines(lines: list[str], result: GuideSyncRunResult) -> None:
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


def append_provider_lines(lines: list[str], result: GuideSyncRunResult) -> None:
    lines.extend(["", "## Provider", ""])
    if result.provider_metadata:
        lines.append(f"- Provider: `{result.provider_metadata.provider}`")
        lines.append(f"- Model: `{result.provider_metadata.model}`")
        lines.append(f"- Latency: `{result.provider_metadata.latency_ms}ms`")


def append_run_configuration_lines(lines: list[str], result: GuideSyncRunResult) -> None:
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


def artifact_payloads(result: GuideSyncRunResult) -> dict[str, str]:
    payloads: dict[str, str] = {}
    if "md" in result.request.report.formats:
        payloads["technical-report.md"] = render_markdown(result)
    return payloads


def publication_report_payload(result: GuideSyncRunResult) -> str | None:
    report = build_publication_report(result)
    if report is None:
        return None
    return json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


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
            "technical-report.md": "text/markdown; charset=utf-8",
            "report.json": "application/json; charset=utf-8",
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
        if parsed.scheme in {"s3", "http", "https"}:
            continue
        if parsed.scheme:
            raise ValueError(f"Unsupported artifact URI scheme: {parsed.scheme}")
        path = Path(uri)
        if not path.is_file():
            raise FileNotFoundError(path)
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
    publication_payload = publication_report_payload(result)
    artifacts.update(write_s3_existing_artifacts(result, artifacts, config))
    result_with_artifacts = result.model_copy(update={"artifacts": artifacts})
    artifacts.update(
        write_s3_reports(
            result_with_artifacts,
            artifact_payloads(result_with_artifacts),
            config,
        )
    )
    if publication_payload is not None:
        artifacts.update(
            write_s3_reports(
                result_with_artifacts,
                {"report.json": publication_payload},
                config,
            )
        )
    if "json" in result.request.report.formats:
        json_payload = run_json_payload(result, artifacts)
        artifacts.update(write_s3_reports(result, {"run.json": json_payload}, config))
    return artifacts


def read_artifact(uri: str) -> ArtifactContent:
    parsed = urlparse(uri)
    if parsed.scheme == "s3":
        return read_s3_artifact(parsed.netloc, parsed.path.lstrip("/"))
    if parsed.scheme in {"http", "https"}:
        raise ValueError("Remote public artifact URLs should be opened directly.")
    raise ValueError("Artifact URI must use s3 or HTTP(S).")


def read_s3_artifact(bucket: str, key: str) -> ArtifactContent:
    config = artifact_storage_config()
    client = boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
    )
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            raise FileNotFoundError(f"s3://{bucket}/{key}") from exc
        raise ValueError(
            f"S3 artifact read failed ({error_code or 'unknown error'})."
        ) from exc
    except BotoCoreError as exc:
        raise ValueError("S3 artifact read failed.") from exc
    content_type = response.get("ContentType") or content_type_for_name(key)
    return ArtifactContent(
        body=response["Body"].read(),
        content_type=content_type,
    )


def content_type_for_name(name: str) -> str:
    if name.endswith(".md"):
        return "text/markdown; charset=utf-8"
    if name.endswith(".html"):
        return "text/html; charset=utf-8"
    if name.endswith(".json"):
        return "application/json; charset=utf-8"
    return mimetypes.guess_type(name)[0] or "application/octet-stream"
