from __future__ import annotations

import asyncio
import json
from pathlib import Path

from guidesync_agent.benchmarks import run_suite, write_results
from guidesync_agent.schemas import BenchmarkSuite

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_benchmark_suite_writes_json_and_csv(tmp_path: Path) -> None:
    suite = BenchmarkSuite.model_validate_json(
        (PROJECT_ROOT / "fixtures/benchmark-suite.json").read_text(encoding="utf-8")
    )

    results = asyncio.run(run_suite(suite, tmp_path))
    write_results(results, tmp_path)

    assert len(results) == 1
    assert results[0].status == "completed"
    assert (tmp_path / "benchmark-results.json").exists()
    assert (tmp_path / "benchmark-summary.csv").exists()

    payload = json.loads((tmp_path / "benchmark-results.json").read_text(encoding="utf-8"))
    assert payload[0]["score"]["evidence_use"] >= 1
