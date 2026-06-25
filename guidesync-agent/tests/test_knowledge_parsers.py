from __future__ import annotations

import subprocess
from pathlib import Path

from guidesync_agent.knowledge import build_knowledge_snapshot
from guidesync_agent.knowledge_parsers import parse_code_file
from guidesync_agent.schemas import KnowledgeIndexRequest, RepositoryInput


def run_git(repo: Path | None, args: list[str]) -> None:
    command = ["git", *args] if repo is None else ["git", "-C", str(repo), *args]
    subprocess.run(command, check=True, capture_output=True, text=True)


def test_regex_parser_extracts_typescript_symbols_imports_and_exports() -> None:
    parsed = parse_code_file(
        "src/panel.tsx",
        "\n".join(
            [
                "import React from 'react';",
                "import { createRoot } from 'react-dom/client';",
                "export interface TerminalProps { title: string }",
                "export function TerminalPanel() { return null; }",
                "const helper = () => null;",
            ]
        ),
    )

    assert parsed.parser_name == "regex-code-parser"
    assert parsed.language == "typescript"
    assert [item.name for item in parsed.symbols] == [
        "TerminalProps",
        "TerminalPanel",
        "helper",
    ]
    assert [item.symbol_kind for item in parsed.symbols] == [
        "interface",
        "function",
        "variable",
    ]
    assert [item.module for item in parsed.imports] == ["react", "react-dom/client"]
    assert parsed.exports == ["TerminalProps", "TerminalPanel"]


def test_regex_parser_extracts_python_symbols_and_imports() -> None:
    parsed = parse_code_file(
        "src/domains.py",
        "\n".join(
            [
                "import os",
                "from pathlib import Path",
                "class DomainService:",
                "    pass",
                "def configure_domain(name: str) -> str:",
                "    return name",
            ]
        ),
    )

    assert parsed.language == "python"
    assert [item.module for item in parsed.imports] == ["os", "pathlib"]
    assert [item.name for item in parsed.symbols] == ["DomainService", "configure_domain"]
    assert [item.line_number for item in parsed.symbols] == [3, 5]


def test_knowledge_index_skips_code_files_and_stores_doc_refs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "src").mkdir(parents=True)
    (repo / "docs" / "guide.md").write_text(
        "# Terminal workflow\n\nUse command review before applying terminal actions.\n",
        encoding="utf-8",
    )
    (repo / "src" / "panel.ts").write_text(
        "import { shell } from './shell';\nexport function TerminalPanel() { return shell; }\n",
        encoding="utf-8",
    )

    snapshot = build_knowledge_snapshot(
        KnowledgeIndexRequest(
            repositories=[
                RepositoryInput(
                    name="fixture",
                    path=repo,
                    paths=["docs", "src"],
                )
            ]
        )
    )

    assert snapshot.run.summary.files == 1
    assert snapshot.run.summary.documents == 1
    assert snapshot.run.summary.sections == 1
    assert not any(node.path == "src/panel.ts" for node in snapshot.nodes)

    file_node = next(node for node in snapshot.nodes if node.path == "docs/guide.md")
    chunk = next(item for item in snapshot.chunks if item.path == "docs/guide.md")

    assert file_node.metadata["extractor"] == "documentation-ref-indexer"
    assert file_node.metadata["tagger"] == "tfidf-v1"
    assert "terminal" in file_node.metadata["tags"]
    assert {"terminal", "workflow"} <= set(file_node.metadata["search_terms"])
    assert chunk.metadata["extractor"] == "markdown-section-ref-indexer"
    assert chunk.metadata["tagger"] == "tfidf-v1"
    assert "Use command review" in chunk.text
    assert "applying terminal actions" in chunk.text
    assert "export function TerminalPanel" not in chunk.text


def test_repository_cache_index_checks_out_repository_before_scanning(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "repository-cache"))
    source = tmp_path / "source"
    (source / "docs").mkdir(parents=True)
    (source / "src").mkdir()
    (source / "docs" / "guide.md").write_text(
        "# Terminal workflow\n\nThe integrated terminal supports command review.\n",
        encoding="utf-8",
    )
    (source / "src" / "panel.ts").write_text(
        "export function TerminalPanel() { return null; }\n",
        encoding="utf-8",
    )
    run_git(None, ["init", str(source)])
    run_git(source, ["config", "user.email", "test@example.com"])
    run_git(source, ["config", "user.name", "GuideSync Test"])
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Add fixture files"])
    run_git(source, ["branch", "-M", "main"])

    snapshot = build_knowledge_snapshot(
        KnowledgeIndexRequest(
            repositories=[
                RepositoryInput(
                    name="fixture",
                    project_id="project-cache-test",
                    repository_id="repo-cache-test",
                    url=str(source),
                    ref="main",
                    paths=["docs"],
                )
            ],
            max_files=10,
        )
    )

    assert snapshot.run.summary.files == 1
    assert snapshot.run.summary.warnings == []
    assert any(node.path == "docs/guide.md" for node in snapshot.nodes)
