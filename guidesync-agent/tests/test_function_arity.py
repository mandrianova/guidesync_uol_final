from __future__ import annotations

import ast
from pathlib import Path

HIGH_ARITY_ALLOWLIST = {
    ("controllers/evaluations.py", "list_runs"): (
        6,
        "controller mirrors the public evaluation query filters",
    ),
    ("routes/evaluations.py", "list_runs"): (
        6,
        "FastAPI exposes independent query parameters",
    ),
    ("services/evaluation_conditions.py", "condition_protocol"): (
        6,
        "isolated declarative condition builder",
    ),
    ("services/evaluation_experiment.py", "build_experiment_manifest"): (
        7,
        "isolated experiment manifest builder",
    ),
    ("services/evaluation_metrics.py", "paired_ablation_delta"): (
        7,
        "isolated paired-metric calculation",
    ),
    ("services/evaluation_records.py", "list_runs"): (
        7,
        "forwards the evaluation query contract to storage",
    ),
    ("services/knowledge_annotation/extraction.py", "extract_keyphrases"): (
        6,
        "isolated NLP pipeline operation with explicit dependencies",
    ),
    ("services/knowledge_annotation/records.py", "annotation_metadata"): (
        6,
        "isolated annotation aggregation builder",
    ),
    ("services/knowledge_retrieval.py", "score_metadata_group"): (
        7,
        "algorithm weights and term sets remain explicit",
    ),
    ("services/project_profile_evaluation.py", "profile_findings"): (
        6,
        "isolated validation aggregation over distinct finding sets",
    ),
    ("services/retrieval_evaluation.py", "evaluate_retrieval"): (
        6,
        "evaluation corpus boundary keeps independent collections explicit",
    ),
    ("storage/database_evaluations.py", "list_runs"): (
        6,
        "database adapter implements the evaluation query protocol",
    ),
    ("storage/protocols.py", "list_runs"): (
        6,
        "storage protocol declares independent query filters",
    ),
    ("tools/browser.py", "capture_ui_screenshot"): (
        6,
        "model-facing tool inputs must stay flat primitives",
    ),
    ("tools/code_change_agent.py", "read_raw_diff"): (
        7,
        "model-facing tool inputs must stay flat primitives",
    ),
    ("tools/registry.py", "read_only_tool"): (
        6,
        "isolated declarative tool-definition builder",
    ),
    ("tools/repository.py", "read_diff_window"): (
        7,
        "bounded repository-tool boundary exposes window controls",
    ),
}


def test_high_arity_functions_are_explicitly_justified() -> None:
    source_root = Path(__file__).parents[1] / "src" / "guidesync_agent"
    observed: dict[tuple[str, str], tuple[int, str]] = {}

    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            arguments = [
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            ]
            count = sum(argument.arg not in {"self", "cls"} for argument in arguments)
            if count <= 5:
                continue
            key = (path.relative_to(source_root).as_posix(), node.name)
            reason = HIGH_ARITY_ALLOWLIST.get(key, (count, ""))[1]
            observed[key] = (count, reason)

    assert observed == HIGH_ARITY_ALLOWLIST
