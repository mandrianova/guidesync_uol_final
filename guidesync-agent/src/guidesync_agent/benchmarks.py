from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path

from guidesync_agent.pipeline import run_guidesync
from guidesync_agent.schemas import (
    BenchmarkResult,
    BenchmarkScore,
    BenchmarkSuite,
    GuideSyncRunRequest,
)


def score_result(
    status: str,
    findings_count: int,
    has_update: bool,
    evidence_refs: int,
) -> BenchmarkScore:
    if status != "completed" or not has_update:
        return BenchmarkScore(
            factuality=0,
            evidence_use=0,
            documentation_usefulness=0,
            traceability=0,
            reviewer_effort=0,
        )
    return BenchmarkScore(
        factuality=2,
        evidence_use=min(3, evidence_refs),
        documentation_usefulness=2,
        traceability=3 if evidence_refs else 1,
        reviewer_effort=3 if findings_count == 0 else 2 if findings_count <= 2 else 1,
    )


async def run_suite(suite: BenchmarkSuite, output_dir: Path) -> list[BenchmarkResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[BenchmarkResult] = []
    for case in suite.cases:
        for provider in suite.providers:
            request_data = case.request.model_copy(deep=True)
            run_id = f"{case.id}-{provider.provider.value}-{provider.model.replace(':', '-')}"
            request = GuideSyncRunRequest.model_validate(
                {
                    **request_data.model_dump(),
                    "run_id": run_id,
                    "provider": provider.model_dump(),
                    "report": {
                        **request_data.report.model_dump(),
                        "output_dir": str(output_dir / case.id / provider.model.replace(":", "-")),
                    },
                }
            )
            run = await run_guidesync(request)
            evidence_refs = len(run.update.evidence_used) if run.update else 0
            score = score_result(
                run.status,
                len(run.findings),
                bool(run.update),
                evidence_refs,
            )
            results.append(
                BenchmarkResult(
                    suite=suite.name,
                    case_id=case.id,
                    provider=provider.provider.value,
                    model=provider.model,
                    run_id=run.run_id,
                    status=run.status,
                    score=score,
                    findings=run.findings,
                    latency_ms=run.provider_metadata.latency_ms if run.provider_metadata else None,
                    artifacts=run.artifacts,
                )
            )
    return results


def write_results(results: list[BenchmarkResult], output_dir: Path) -> None:
    json_path = output_dir / "benchmark-results.json"
    json_path.write_text(
        json.dumps([result.model_dump(mode="json") for result in results], indent=2) + "\n",
        encoding="utf-8",
    )
    csv_path = output_dir / "benchmark-summary.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "suite",
                "case_id",
                "provider",
                "model",
                "status",
                "factuality",
                "evidence_use",
                "documentation_usefulness",
                "traceability",
                "reviewer_effort",
                "latency_ms",
            ]
        )
        for result in results:
            writer.writerow(
                [
                    result.suite,
                    result.case_id,
                    result.provider,
                    result.model,
                    result.status,
                    result.score.factuality,
                    result.score.evidence_use,
                    result.score.documentation_usefulness,
                    result.score.traceability,
                    result.score.reviewer_effort,
                    result.latency_ms,
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GuideSync model benchmarks.")
    parser.add_argument("suite", type=Path, help="Path to benchmark suite JSON.")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/benchmarks/latest"))
    args = parser.parse_args()
    suite = BenchmarkSuite.model_validate_json(args.suite.read_text(encoding="utf-8"))
    results = asyncio.run(run_suite(suite, args.output_dir))
    write_results(results, args.output_dir)
    print(args.output_dir)


if __name__ == "__main__":
    main()
