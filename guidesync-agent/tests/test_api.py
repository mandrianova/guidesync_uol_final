from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from guidesync_agent import knowledge as knowledge_module
from guidesync_agent.api import app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "fixtures/domain-guide-task.json"


def load_fixture(tmp_path: Path) -> dict:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["run_id"] = "pytest-api-domain-guide"
    payload["report"]["output_dir"] = str(tmp_path / "api-run")
    return payload


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "guidesync-agent"}


def test_create_and_get_run(tmp_path: Path) -> None:
    client = TestClient(app)

    create_response = client.post("/runs", json=load_fixture(tmp_path))

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["run_id"] == "pytest-api-domain-guide"
    assert created["status"] == "completed"
    assert created["update"]["title"] == "Custom domain management updates"
    assert Path(created["artifacts"]["report.md"]).exists()

    get_response = client.get("/runs/pytest-api-domain-guide")

    assert get_response.status_code == 200
    assert get_response.json()["run_id"] == "pytest-api-domain-guide"

    list_response = client.get("/runs")

    assert list_response.status_code == 200
    assert any(item["run_id"] == "pytest-api-domain-guide" for item in list_response.json())

    markdown_response = client.get("/runs/pytest-api-domain-guide/artifacts/report.md")

    assert markdown_response.status_code == 200
    assert "text/markdown" in markdown_response.headers["content-type"]
    assert "# GuideSync domain release notes" in markdown_response.text

    print_response = client.get("/runs/pytest-api-domain-guide/artifacts/report.html?print=1")

    assert print_response.status_code == 200
    assert "text/html" in print_response.headers["content-type"]
    assert "GuideSync release notes report" in print_response.text
    assert "<pre>" not in print_response.text
    assert "window.print()" in print_response.text


def test_project_run_is_created_as_tracked_task(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'runs.db'}")
    client = TestClient(app)
    project_response = client.post(
        "/projects",
        json={
            "name": "Async API project",
            "repositories": [
                {
                    "id": "repo-api-async",
                    "name": "repo",
                    "url": "https://github.com/example/repo",
                    "default_branch": "main",
                    "paths": [],
                }
            ],
            "documentation": [
                {
                    "id": "doc-api-async",
                    "name": "docs",
                    "content": "Product context.",
                }
            ],
        },
    )
    project_id = project_response.json()["id"]

    run_response = client.post(
        f"/projects/{project_id}/runs",
        json={
            "goal": "Create an async report task.",
            "mode": "default_branch_period",
            "since": "2026-06-01",
            "until": None,
            "branches": {},
            "provider": {"provider": "mock", "model": "mock:deterministic"},
        },
    )

    assert run_response.status_code == 200
    created = run_response.json()
    assert created["run_id"].startswith(f"{project_id}-")
    assert created["status"] == "queued"
    assert created["created_at"]

    get_response = client.get(f"/runs/{created['run_id']}")

    assert get_response.status_code == 200
    assert get_response.json()["request"]["provider"]["provider"] == "mock"

    list_response = client.get(f"/projects/{project_id}/runs")

    assert list_response.status_code == 200
    assert any(item["run_id"] == created["run_id"] for item in list_response.json())


def test_project_run_uses_environment_provider_when_request_provider_is_omitted(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'providers.db'}")
    monkeypatch.setenv("GUIDESYNC_AGENT_PROVIDER", "local_http")
    monkeypatch.setenv("GUIDESYNC_AGENT_MODEL", "google/gemma-4-31b-qat")
    monkeypatch.setenv("GUIDESYNC_AGENT_BASE_URL", "http://localhost:1234/api/v1/chat")
    client = TestClient(app)
    project_response = client.post(
        "/projects",
        json={
            "name": "Provider defaults project",
            "repositories": [
                {
                    "id": "repo-provider-defaults",
                    "name": "pydantic-ai",
                    "url": "https://github.com/pydantic/pydantic-ai",
                    "default_branch": "main",
                    "paths": [],
                }
            ],
            "documentation": [
                {
                    "id": "doc-provider-defaults",
                    "name": "docs",
                    "content": "Product context.",
                }
            ],
        },
    )
    project_id = project_response.json()["id"]

    run_response = client.post(
        f"/projects/{project_id}/runs",
        json={
            "goal": "Create a provider default report task.",
            "mode": "default_branch_period",
            "since": "2026-06-01",
            "until": None,
            "branches": {},
        },
    )

    assert run_response.status_code == 200
    created = run_response.json()
    get_response = client.get(f"/runs/{created['run_id']}")

    assert get_response.status_code == 200
    request = get_response.json()["request"]
    assert request["provider"]["provider"] == "local_http"
    assert request["provider"]["model"] == "google/gemma-4-31b-qat"


def test_built_in_default_model_is_read_only(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'models.db'}")
    client = TestClient(app)

    profiles_response = client.get("/settings/models")

    assert profiles_response.status_code == 200
    default_profile = profiles_response.json()[0]
    assert default_profile["id"] == "global-default"

    update_response = client.put(
        "/settings/models/global-default",
        json={
            "name": "Edited default",
            "provider": "mock",
            "model": "mock:deterministic",
            "timeout_seconds": 60,
        },
    )
    delete_response = client.delete("/settings/models/global-default")

    assert update_response.status_code == 403
    assert delete_response.status_code == 403


def test_knowledge_index_search_and_context_pack(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'knowledge.db'}")
    repo = tmp_path / "sample-repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "docs" / "guide.md").write_text(
        "# Domain setup\n\nUse the terminal workflow to configure custom domains.\n",
        encoding="utf-8",
    )
    (repo / "src" / "domains.py").write_text(
        "def configure_domain(name: str) -> str:\n"
        "    return f'configured {name}'\n",
        encoding="utf-8",
    )
    client = TestClient(app)

    index_response = client.post(
        "/knowledge/index-runs",
        json={
            "repositories": [
                {
                    "name": "sample",
                    "path": str(repo),
                    "paths": ["docs", "src"],
                }
            ],
            "max_files": 20,
        },
    )

    assert index_response.status_code == 200
    index_run = index_response.json()
    assert index_run["status"] == "completed"
    assert index_run["summary"]["files"] == 2
    assert index_run["summary"]["nodes"] >= 4

    search_response = client.post(
        "/knowledge/search",
        json={"query": "terminal custom domains", "limit": 5},
    )

    assert search_response.status_code == 200
    results = search_response.json()
    assert results
    guide_result = next(item for item in results if item["node"]["path"] == "docs/guide.md")
    assert "custom domains" in guide_result["matched_text"]

    context_response = client.post(
        "/knowledge/context-pack",
        json={"goal": "How does domain setup work?", "limit": 5, "token_budget": 500},
    )

    assert context_response.status_code == 200
    context_pack = context_response.json()
    assert context_pack["results"]
    assert context_pack["nodes"]
    assert any(edge["edge_type"] == "contains" for edge in context_pack["edges"])


def test_project_knowledge_index_uses_saved_project_repositories(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'project-kg.db'}")
    monkeypatch.chdir(tmp_path)
    repo = Path("cached-repo")
    (repo / "docs").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "docs" / "guide.md").write_text(
        "# Terminal workflows\n\nThe terminal panel supports command review.\n",
        encoding="utf-8",
    )
    (repo / "src" / "ignored.py").write_text(
        "def ignored_symbol() -> None:\n    pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        knowledge_module,
        "ensure_github_repository_cache",
        lambda _url, _owner, _repo: repo,
    )
    monkeypatch.setattr(
        knowledge_module,
        "checkout_repository_ref",
        lambda _root, _repository, _warnings: None,
    )
    client = TestClient(app)
    project_response = client.post(
        "/projects",
        json={
            "name": "Knowledge project",
            "repositories": [
                {
                    "id": "repo-knowledge",
                    "name": "knowledge-repo",
                    "url": "https://github.com/example/knowledge-repo",
                    "default_branch": "main",
                    "paths": ["docs"],
                }
            ],
            "documentation": [
                {
                    "id": "doc-knowledge",
                    "name": "product-context",
                    "content": "Terminal workflows are user-facing.",
                }
            ],
        },
    )
    project_id = project_response.json()["id"]

    index_response = client.post(
        f"/projects/{project_id}/knowledge/index-runs",
        json={"max_files": 10},
    )

    assert index_response.status_code == 200
    index_run = index_response.json()
    assert index_run["project_id"] == project_id
    assert index_run["status"] == "completed"
    assert index_run["summary"]["repositories"] == 1
    assert index_run["summary"]["files"] == 1
    assert index_run["summary"]["documentation_sources"] == 1
    assert index_run["summary"]["warnings"] == []
    assert index_run["request"]["repositories"][0]["paths"] == ["docs"]

    list_response = client.get(f"/projects/{project_id}/knowledge/index-runs")

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [index_run["id"]]

    search_response = client.post(
        "/knowledge/search",
        json={"project_id": project_id, "query": "terminal workflows", "limit": 5},
    )

    assert search_response.status_code == 200
    assert any(item["node"]["path"] == "docs/guide.md" for item in search_response.json())
