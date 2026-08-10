from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path

from guidesync_agent.benchmarks import score_result
from guidesync_agent.pipeline import run_guidesync
from guidesync_agent.schemas import (
    GuideSyncRunRequest,
    ModelComparisonReport,
    ModelComparisonRequest,
    ModelComparisonRun,
    ProviderConfig,
)

PROMPT_VERSIONS = {
    "context_summary": "context-summary-v1",
    "file_change_summarizer": "file-change-summarizer-v1",
    "validation": "workflow-validation-v1",
}


async def run_model_comparison(
    request: ModelComparisonRequest,
    output_dir: Path,
) -> ModelComparisonReport:
    await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
    input_bundle_id = request.input_bundle_id or input_bundle_id_for_request(request.base_request)
    runs: list[ModelComparisonRun] = []
    for provider in request.providers:
        run_request = comparison_run_request(
            request.base_request,
            provider,
            input_bundle_id=input_bundle_id,
            output_dir=output_dir,
        )
        result = await run_guidesync(run_request)
        score = score_result(
            result.status,
            len(result.findings),
            result.update is not None,
            len(result.update.evidence_used) if result.update else 0,
        )
        runs.append(
            ModelComparisonRun(
                input_bundle_id=input_bundle_id,
                provider=provider.provider.value,
                model=provider.model,
                run_id=result.run_id,
                status=result.status,
                score=score,
                latency_ms=(
                    result.provider_metadata.latency_ms if result.provider_metadata else None
                ),
                cost=result.provider_metadata.cost if result.provider_metadata else {},
                prompt_versions=PROMPT_VERSIONS,
                findings_count=len(result.findings),
                artifacts=result.artifacts,
            )
        )
    report = ModelComparisonReport(
        name=request.name,
        input_bundle_id=input_bundle_id,
        rubric_version=request.rubric_version,
        runs=runs,
        recommendation=recommendation_for(runs),
    )
    return report.model_copy(
        update={"artifacts": write_model_comparison_report(report, output_dir)}
    )


def run_model_comparison_sync(
    request: ModelComparisonRequest,
    output_dir: Path,
) -> ModelComparisonReport:
    return asyncio.run(run_model_comparison(request, output_dir))


def comparison_run_request(
    base_request: GuideSyncRunRequest,
    provider: ProviderConfig,
    *,
    input_bundle_id: str,
    output_dir: Path,
) -> GuideSyncRunRequest:
    provider_slug = safe_slug(f"{provider.provider.value}-{provider.model}")
    metadata = {
        **provider.metadata,
        "comparison_input_bundle_id": input_bundle_id,
        "comparison_provider_slug": provider_slug,
    }
    run_id = f"{safe_slug(base_request.run_id)}-{provider_slug}"
    return base_request.model_copy(
        deep=True,
        update={
            "run_id": run_id,
            "provider": provider.model_copy(update={"metadata": metadata}),
            "report": base_request.report.model_copy(
                update={"output_dir": output_dir / provider_slug}
            ),
        },
    )


def input_bundle_id_for_request(request: GuideSyncRunRequest) -> str:
    payload = request.model_dump(mode="json")
    payload.pop("run_id", None)
    payload.pop("provider", None)
    report = payload.get("report")
    if isinstance(report, dict):
        report.pop("output_dir", None)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"input-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def write_model_comparison_report(
    report: ModelComparisonReport,
    output_dir: Path,
) -> dict[str, str]:
    json_path = output_dir / "model-comparison.json"
    markdown_path = output_dir / "model-comparison.md"
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_model_comparison_markdown(report), encoding="utf-8")
    return {
        "model-comparison.json": str(json_path),
        "model-comparison.md": str(markdown_path),
    }


def render_model_comparison_markdown(report: ModelComparisonReport) -> str:
    lines = [
        f"# {report.name}",
        "",
        f"- Input bundle: `{report.input_bundle_id}`",
        f"- Rubric: `{report.rubric_version}`",
        f"- Recommendation: {report.recommendation}",
        "",
        "## Runs",
        "",
    ]
    for run in report.runs:
        lines.extend(
            [
                f"### {run.provider} / {run.model}",
                "",
                f"- Run: `{run.run_id}`",
                f"- Status: `{run.status}`",
                f"- Latency: `{run.latency_ms if run.latency_ms is not None else 'n/a'}ms`",
                f"- Cost: `{json.dumps(run.cost, sort_keys=True)}`",
                f"- Findings: `{run.findings_count}`",
                (
                    "- Score: "
                    f"factuality `{run.score.factuality}`, "
                    f"evidence `{run.score.evidence_use}`, "
                    f"docs `{run.score.documentation_usefulness}`, "
                    f"traceability `{run.score.traceability}`, "
                    f"reviewer effort `{run.score.reviewer_effort}`"
                ),
                "- Prompt versions:",
            ]
        )
        lines.extend(
            f"  - `{name}`: `{version}`"
            for name, version in sorted(run.prompt_versions.items())
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def recommendation_for(runs: list[ModelComparisonRun]) -> str:
    if not runs:
        return "No runs were completed."
    best = max(
        runs,
        key=lambda run: (
            run.score.factuality
            + run.score.evidence_use
            + run.score.documentation_usefulness
            + run.score.traceability
            + run.score.reviewer_effort,
            -(run.latency_ms or 0),
        ),
    )
    return (
        f"Prefer {best.provider} / {best.model} for this fixture unless manual review "
        "finds quality issues not captured by the rubric."
    )


def safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")[:80] or "run"
