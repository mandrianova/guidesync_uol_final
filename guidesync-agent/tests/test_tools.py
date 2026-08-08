from __future__ import annotations

import subprocess
from pathlib import Path

from storage_test_utils import sqlite_database_url

from guidesync_agent.knowledge import build_knowledge_snapshot
from guidesync_agent.schemas import (
    KnowledgeIndexRequest,
    ProjectCreate,
    ProjectRepository,
    RepositoryInput,
)
from guidesync_agent.services.repository_cache import RepositoryCacheService
from guidesync_agent.storage import DatabaseProjectStore, create_knowledge_store
from guidesync_agent.tools.factory import ToolFactory
from guidesync_agent.tools.knowledge import (
    KnowledgeBaseSearchRequest,
    get_knowledge_document_ref,
    read_knowledge_document_window,
    search_knowledge_base,
)
from guidesync_agent.tools.repository import (
    list_changed_files,
    read_diff_window,
    read_file_window,
    search_repository,
)
from guidesync_agent.tools.repository_filesystem import (
    TextReadOptions,
    context_from_project,
    directory_tree,
    get_file_info,
    list_allowed_directories,
    list_directory,
    list_directory_with_sizes,
    read_multiple_files,
    read_text_file,
    search_files,
)
from guidesync_agent.tools.validation import validate_tool_result


def run_git(repo: Path | None, args: list[str]) -> None:
    command = ["git", *args] if repo is None else ["git", "-C", str(repo), *args]
    subprocess.run(command, check=True, capture_output=True, text=True)


def create_source_repository(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "docs").mkdir(parents=True)
    (source / "src").mkdir()
    (source / "docs" / "guide.md").write_text(
        "# Guide\n\nInitial terminal workflow.\n",
        encoding="utf-8",
    )
    (source / "src" / "app.py").write_text("print('initial')\n", encoding="utf-8")
    (source / "assets.bin").write_bytes(b"\x00\x01\x02")
    (source / ".env").write_text("GUIDESYNC_TOKEN=secret\n", encoding="utf-8")
    run_git(None, ["init", str(source)])
    run_git(source, ["config", "user.email", "test@example.com"])
    run_git(source, ["config", "user.name", "GuideSync Test"])
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Initial docs"])
    (source / "docs" / "guide.md").write_text(
        "# Guide\n\nInitial terminal workflow.\n\nDocument bounded tools.\n",
        encoding="utf-8",
    )
    (source / "src" / "app.py").write_text(
        "print('initial')\nprint('terminal tools')\n",
        encoding="utf-8",
    )
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Update docs and app"])
    run_git(source, ["branch", "-M", "main"])
    return source


def create_project(monkeypatch, tmp_path: Path) -> tuple[str, str]:
    database_url = sqlite_database_url(tmp_path / "tools.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "cache"))
    source = create_source_repository(tmp_path)
    project = DatabaseProjectStore(database_url).save(
        ProjectCreate(
            name="Tools project",
            repositories=[
                ProjectRepository(
                    id="repo-tools",
                    name="fixture",
                    url=str(source),
                    default_branch="main",
                    analysis_paths=["docs", "src"],
                )
            ],
        )
    )
    return project.id, "repo-tools"


def test_repository_tools_are_bounded_and_reject_unsafe_paths(monkeypatch, tmp_path: Path) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)

    window = read_file_window(project_id, repository_id, "docs/guide.md", offset=0, limit=12)
    next_window = read_file_window(
        project_id,
        repository_id,
        "docs/guide.md",
        offset=window.pagination.next_offset or 0,
        limit=20,
    )
    outside = read_file_window(project_id, repository_id, "../secret.txt")
    binary = read_file_window(project_id, repository_id, "assets.bin")

    assert window.error is None
    assert window.content == "# Guide\n\nIni"
    assert window.pagination.truncated is True
    assert next_window.content.startswith("tial terminal")
    assert outside.error is not None
    assert outside.error.code == "path_outside_repository"
    assert binary.error is not None
    assert binary.error.code == "binary_file"


def test_repository_diff_search_and_changed_files_tools(monkeypatch, tmp_path: Path) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)

    changed = list_changed_files(project_id, repository_id)
    diff = read_diff_window(project_id, repository_id, path="docs/guide.md", limit=200)
    search = search_repository(
        project_id,
        repository_id,
        "terminal",
        path_filters=["docs", "src"],
        limit=1,
    )

    assert changed.error is None
    assert {file.path for file in changed.files} == {"docs/guide.md", "src/app.py"}
    assert diff.error is None
    assert "+Document bounded tools." in diff.diff
    assert search.error is None
    assert search.total >= 2
    assert search.truncated is True
    assert len(search.matches) == 1


def test_repository_filesystem_tools_match_mcp_style_contract(  # noqa: PLR0915
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)
    context = context_from_project(project_id)
    root_path = f"/repositories/{repository_id}/"

    roots = list_allowed_directories(context)
    root_listing = list_directory(context, root_path)
    sized_listing = list_directory_with_sizes(context, root_path, sort_by="size")
    tree = directory_tree(context, root_path, exclude_patterns=["*.bin"])
    search = search_files(context, root_path, "bounded tools")
    hidden_search = search_files(context, root_path, "GUIDESYNC_TOKEN")
    head = read_text_file(
        context,
        f"{root_path}docs/guide.md",
        options=TextReadOptions(head=2),
    )
    tail = read_text_file(
        context,
        f"{root_path}docs/guide.md",
        options=TextReadOptions(tail=1),
    )
    window = read_text_file(
        context,
        f"{root_path}docs/guide.md",
        options=TextReadOptions(start_line=3, line_count=2),
    )
    capped = read_text_file(
        context,
        f"{root_path}docs/guide.md",
        options=TextReadOptions(max_chars=24),
    )
    invalid_window = read_text_file(
        context,
        f"{root_path}docs/guide.md",
        options=TextReadOptions(head=1, tail=1),
    )
    multi = read_multiple_files(
        context,
        [
            f"{root_path}docs/guide.md",
            f"{root_path}missing.md",
        ],
    )
    info = get_file_info(context, f"{root_path}docs/guide.md")
    traversal = read_text_file(context, f"{root_path}../secret.txt")

    assert roots.error is None
    assert "Allowed directories:" in roots.content
    assert root_path in roots.content
    assert root_listing.error is None
    assert "[DIR] docs" in root_listing.content
    assert "[DIR] src" in root_listing.content
    assert ".env" not in root_listing.content
    assert sized_listing.error is None
    assert "Total files:" in sized_listing.content
    assert "Combined size:" in sized_listing.content
    assert tree.error is None
    assert '"children"' in tree.content
    assert "assets.bin" not in tree.content
    assert search.error is None
    assert f"{root_path}docs/guide.md:5: Document bounded tools." in search.content
    assert search.entries[0]["line_number"] == 5
    assert search.entries[0]["evidence_ref"] == f"{root_path}docs/guide.md#L5"
    assert search.evidence_refs[0] == f"{root_path}docs/guide.md#L5"
    assert not any(ref.startswith("repo:") for ref in search.evidence_refs)
    assert search.metadata["backend"] == "ripgrep"
    assert hidden_search.error is None
    assert f"{root_path}.env:1: GUIDESYNC_TOKEN=secret" in hidden_search.content
    assert head.error is None
    assert head.evidence_refs == [f"{root_path}docs/guide.md"]
    assert head.content == "# Guide\n\n"
    assert tail.error is None
    assert "Document bounded tools." in tail.content
    assert window.error is None
    assert window.content == "Initial terminal workflow.\n\n"
    assert window.truncated is True
    assert len(capped.content) <= 24
    assert capped.truncated is True
    assert invalid_window.error is not None
    assert invalid_window.error.code == "invalid_read_window"
    assert multi.error is None
    assert f"{root_path}docs/guide.md:" in multi.content
    assert f"{root_path}missing.md:\nError:" in multi.content
    assert info.error is None
    assert "permissions:" in info.content
    assert traversal.error is not None
    assert traversal.error.code == "path_outside_repository"


def test_knowledge_tools_read_document_windows(monkeypatch, tmp_path: Path) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)
    snapshot = build_knowledge_snapshot(
        KnowledgeIndexRequest(
            project_id=project_id,
            repositories=[
                RepositoryInput(
                    name="fixture",
                    project_id=project_id,
                    repository_id=repository_id,
                    url=str(tmp_path / "source"),
                    ref="main",
                    paths=["docs"],
                )
            ],
        )
    )
    create_knowledge_store().save_snapshot(snapshot)

    results = search_knowledge_base(
        KnowledgeBaseSearchRequest(
            project_id=project_id,
            query="bounded tools",
            limit=3,
        )
    )
    document_id = create_knowledge_store().document_refs(project_id).documents[0].id
    document_ref = get_knowledge_document_ref(document_id)
    window = read_knowledge_document_window(document_id, limit=12)

    assert results
    assert document_ref is not None
    assert document_ref.path == "docs/guide.md"
    assert window.error is None
    assert window.content == "# Guide\n\nIni"
    assert window.pagination.truncated is True


def test_knowledge_search_filters_results_stale_for_current_checkout(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)
    source = tmp_path / "source"
    (source / "docs" / "stale.md").write_text(
        "# Streaming generator generator generator\n\nOld JSONL details.\n",
        encoding="utf-8",
    )
    (source / "docs" / "current.md").write_text(
        "# Streaming generator\n\nCurrent JSONL details.\n",
        encoding="utf-8",
    )
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Add streaming docs"])
    snapshot = build_knowledge_snapshot(
        KnowledgeIndexRequest(
            project_id=project_id,
            repositories=[
                RepositoryInput(
                    name="fixture",
                    project_id=project_id,
                    repository_id=repository_id,
                    url=str(source),
                    ref="main",
                    paths=["docs"],
                )
            ],
        )
    )
    create_knowledge_store().save_snapshot(snapshot)
    cache_root = RepositoryCacheService().cache_path(project_id, repository_id)
    (cache_root / "docs" / "stale.md").write_text(
        "# Replaced page\n\nThe indexed generator section no longer exists.\n",
        encoding="utf-8",
    )

    results = search_knowledge_base(
        KnowledgeBaseSearchRequest(
            project_id=project_id,
            query="streaming generator JSONL",
            limit=1,
        )
    )

    assert len(results) == 1
    assert results[0].node.path == "docs/current.md"


def test_tool_factory_and_validation_wrap_structured_findings(monkeypatch, tmp_path: Path) -> None:
    project_id, repository_id = create_project(monkeypatch, tmp_path)
    factory = ToolFactory(project_id)
    tools = factory.for_workflow("documentation_update")
    result = tools["read_text_file"](f"/repositories/{repository_id}/../secret.txt")
    findings = validate_tool_result("read_text_file", result)

    assert {"read_text_file", "search_files", "search_knowledge_base"} <= set(tools)
    assert "read_file_window" not in tools
    assert "search_repository" not in tools
    assert findings
    assert findings[0].severity == "error"
    assert findings[0].check == "read_text_file.error"
