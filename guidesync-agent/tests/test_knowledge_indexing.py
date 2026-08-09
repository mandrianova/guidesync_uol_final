from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from guidesync_agent.knowledge import build_knowledge_snapshot
from guidesync_agent.schemas import (
    KnowledgeIndexRequest,
    KnowledgeNode,
    ProjectTaxonomy,
    RepositoryInput,
)


def run_git(repo: Path | None, args: list[str]) -> None:
    command = ["git", *args] if repo is None else ["git", "-C", str(repo), *args]
    subprocess.run(command, check=True, capture_output=True, text=True)


@pytest.mark.parametrize("legacy_kind", ["file", "section"])
def test_knowledge_node_rejects_legacy_kinds(legacy_kind: str) -> None:
    with pytest.raises(ValidationError):
        KnowledgeNode.model_validate(
            {
                "id": "node-1",
                "kind": legacy_kind,
                "name": "Documentation",
                "qualified_name": "docs/guide.md",
            }
        )


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
            ],
            taxonomy=ProjectTaxonomy(
                version="taxonomy-test-v1",
                categories=["terminal-workflow"],
                workflows=["command review"],
                domain_terms=["terminal actions"],
            ),
        )
    )

    assert snapshot.run.summary.files == 1
    assert snapshot.run.summary.documents == 1
    assert snapshot.run.summary.sections == 1
    assert not any(node.path == "src/panel.ts" for node in snapshot.nodes)

    file_node = next(node for node in snapshot.nodes if node.path == "docs/guide.md")
    chunk = next(item for item in snapshot.chunks if item.path == "docs/guide.md")

    assert file_node.metadata["extractor"] == "documentation-ref-indexer"
    assert file_node.metadata["annotation_method_id"]
    assert file_node.metadata["taxonomy_version"] == "taxonomy-test-v1"
    assert "tagger" not in file_node.metadata
    assert "tag_token_count" not in file_node.metadata
    assert "terminal" in file_node.metadata["tags"]
    assert "terminal-workflow" in file_node.metadata["categories"]
    assert {"terminal", "workflow"} <= set(file_node.metadata["search_terms"])
    assert chunk.metadata["extractor"] == "markdown-section-ref-indexer"
    assert chunk.metadata["annotation_method_id"]
    assert chunk.metadata["taxonomy_version"] == "taxonomy-test-v1"
    assert "tagger" not in chunk.metadata
    assert "tag_token_count" not in chunk.metadata
    assert "Use command review" in chunk.text
    assert "applying terminal actions" in chunk.text
    assert "export function TerminalPanel" not in chunk.text


def test_knowledge_index_bounds_long_section_names(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    heading = "A" * 300
    (repo / "docs" / "guide.md").write_text(
        f"# {heading}\n\nLong-heading content.\n",
        encoding="utf-8",
    )

    snapshot = build_knowledge_snapshot(
        KnowledgeIndexRequest(
            repositories=[RepositoryInput(name="fixture", path=repo, paths=["docs"])]
        )
    )

    section = next(node for node in snapshot.nodes if node.kind.value == "doc_section")
    assert len(section.name) == 255
    assert section.name.endswith("...")


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
            ]
        )
    )

    assert snapshot.run.summary.files == 1
    assert snapshot.run.summary.annotation_runs > 0
    assert not any(
        "knowledge annotation failed" in warning for warning in snapshot.run.summary.warnings
    )
    assert any(node.path == "docs/guide.md" for node in snapshot.nodes)
