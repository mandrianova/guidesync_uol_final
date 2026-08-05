from __future__ import annotations

import ast
from pathlib import Path


def test_structured_contracts_do_not_define_redundant_ok_fields() -> None:
    schema_root = Path(__file__).parents[1] / "src" / "guidesync_agent" / "schemas"
    offenders: list[str] = []

    for path in schema_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for statement in node.body:
                if (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                    and statement.target.id == "ok"
                ):
                    offenders.append(f"{path.name}:{node.name}")

    assert offenders == []
