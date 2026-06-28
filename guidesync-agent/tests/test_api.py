from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from guidesync_agent.api import app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "fixtures/domain-guide-task.json"


def load_fixture(tmp_path: Path) -> dict:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["run_id"] = "pytest-api-domain-guide"
    payload["report"]["output_dir"] = str(tmp_path / "api-run")
    return payload


def run_git(repo: Path | None, args: list[str]) -> None:
    command = ["git", *args] if repo is None else ["git", "-C", str(repo), *args]
    subprocess.run(command, check=True, capture_output=True, text=True)


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "guidesync-agent"}


def test_root_redirects_to_api_docs() -> None:
    client = TestClient(app)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


def test_legacy_static_frontend_is_not_served() -> None:
    client = TestClient(app)

    response = client.get("/static/app.js")

    assert response.status_code == 404


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
    assert markdown_response.headers["content-disposition"] == 'attachment; filename="report.md"'
    assert "# GuideSync domain release notes" in markdown_response.text

    pdf_response = client.get("/runs/pytest-api-domain-guide/artifacts/report.pdf")

    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"] == "application/pdf"
    assert pdf_response.headers["content-disposition"] == 'attachment; filename="report.pdf"'
    assert pdf_response.content.startswith(b"%PDF")

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
    assert created["status"] == "blocked"
    assert created["created_at"]

    get_response = client.get(f"/runs/{created['run_id']}")

    assert get_response.status_code == 200
    assert get_response.json()["request"]["provider"]["provider"] == "mock"
    workflow_response = client.get(f"/projects/{project_id}/workflow/tasks")
    assert workflow_response.status_code == 200
    assert [task["kind"] for task in workflow_response.json()] == [
        "repository_sync",
        "project_profile",
        "knowledge_index",
        "change_analysis",
        "post_analysis_knowledge_refresh",
    ]

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


def test_project_run_stores_requested_and_effective_model_snapshot(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'run-model.db'}")
    client = TestClient(app)
    project_response = client.post(
        "/projects",
        json={
            "name": "Run model project",
            "repositories": [
                {
                    "id": "repo-run-model",
                    "name": "repo",
                    "url": "https://github.com/example/repo",
                    "default_branch": "main",
                    "paths": [],
                }
            ],
        },
    )
    project_id = project_response.json()["id"]

    run_response = client.post(
        f"/projects/{project_id}/runs",
        json={
            "goal": "Create a model snapshot report task.",
            "mode": "default_branch_period",
            "since": "2026-06-01",
            "until": None,
            "branches": {},
            "task_interface_url": "http://127.0.0.1:5173/#/run",
            "screenshot_policy": "required",
            "requested_model_settings": {
                "model_profile_id": "global-default",
                "provider": "local_http",
                "model": "google/gemma-4-31b-qat",
                "base_url": "http://localhost:1234/api/v1/chat",
                "timeout_seconds": 120,
                "thinking": "medium",
                "metadata": {
                    "context_budget": 120000,
                    "max_output_tokens": 4096,
                    "temperature": 0.2,
                },
            },
        },
    )

    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]
    request = client.get(f"/runs/{run_id}").json()["request"]

    assert request["task_interface_url"] == "http://127.0.0.1:5173/#/run"
    assert request["screenshot_policy"] == "required"
    assert request["requested_model_settings"]["metadata"]["context_budget"] == 120000
    assert request["effective_model_configuration"]["provider"] == "local_http"
    assert request["effective_model_configuration"]["model"] == "google/gemma-4-31b-qat"
    assert request["effective_model_configuration"]["timeout_seconds"] == 120
    assert request["effective_model_configuration"]["thinking"] == "medium"


def test_project_profile_builds_after_project_create_and_update(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'profiles.db'}")
    monkeypatch.setenv("GUIDESYNC_PROJECT_PROFILE_OUTPUT_DIR", str(tmp_path / "profiles"))
    repo = tmp_path / "profile-repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "docs" / "architecture.md").write_text(
        "# System architecture\n\n## Documentation workflow\n\n## Release review\n",
        encoding="utf-8",
    )
    (repo / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    run_git(None, ["init", str(repo)])
    run_git(repo, ["config", "user.email", "test@example.com"])
    run_git(repo, ["config", "user.name", "GuideSync Test"])
    run_git(repo, ["add", "."])
    run_git(repo, ["commit", "-m", "Add profile fixture"])
    run_git(repo, ["branch", "-M", "main"])
    client = TestClient(app)

    project_response = client.post(
        "/projects",
        json={
            "name": "Profile project",
            "description": "A project used to validate automatic baseline profiles.",
            "audience": "developers",
            "documentation_instructions": "Keep updates concise.",
            "knowledge_base_path": "docs/",
            "analysis_paths": ["src/", "docs/"],
            "repositories": [
                {
                    "id": "repo-profile",
                    "name": "profile-repo",
                    "url": str(repo),
                    "default_branch": "main",
                    "analysis_paths": ["src/", "docs/"],
                }
            ],
        },
    )
    project_id = project_response.json()["id"]

    profile_response = client.get(f"/projects/{project_id}/profile")

    assert profile_response.status_code == 200
    profile = profile_response.json()
    assert profile["status"] == "completed"
    assert profile["version"] == 1
    assert profile["summary"]
    assert "System architecture" in profile["architecture"]
    assert "Documentation workflow" in profile["workflows"]
    assert profile["key_terms"]
    assert profile["repository_map"][0]["repository_id"] == "repo-profile"
    assert profile["source_refs"][0]["commit_sha"]
    assert profile["model_metadata"]["provider"] == "fake"
    assert profile["tool_trace_refs"]
    assert profile["validation_findings"] == []
    assert Path(profile["artifact_uris"]["profile.json"]).exists()
    assert "## Repository map" in Path(profile["artifact_uris"]["profile.md"]).read_text(
        encoding="utf-8"
    )

    update_response = client.put(
        f"/projects/{project_id}",
        json={
            "name": "Profile project",
            "description": "A project used to validate automatic baseline profiles.",
            "audience": "business_analysts",
            "documentation_instructions": "Focus on operational impact.",
            "knowledge_base_path": "docs/",
            "analysis_paths": ["src/", "docs/"],
            "repositories": [
                {
                    "id": "repo-profile",
                    "name": "profile-repo",
                    "url": str(repo),
                    "default_branch": "main",
                    "analysis_paths": ["src/", "docs/"],
                }
            ],
        },
    )

    assert update_response.status_code == 200
    rebuilt_profile = client.get(f"/projects/{project_id}/profile").json()
    assert rebuilt_profile["version"] == 2
    assert rebuilt_profile["status"] == "completed"


def test_project_create_queues_profile_when_background_queue_is_enabled(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'queued.db'}")
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_SYNC_QUEUE_URL", "http://queue.example/test")
    sent_messages = []

    class FakeSqs:
        def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict[str, str]:
            sent_messages.append(json.loads(MessageBody))
            return {"MessageId": f"message-{len(sent_messages)}"}

    monkeypatch.setattr(
        "guidesync_agent.services.repository_tasks.boto3.client",
        lambda *_, **__: FakeSqs(),
    )
    client = TestClient(app)

    project_response = client.post(
        "/projects",
        json={
            "name": "Queued profile project",
            "repositories": [
                {
                    "id": "repo-queued",
                    "name": "queued-repo",
                    "url": "https://github.com/example/queued-repo",
                    "default_branch": "main",
                }
            ],
        },
    )

    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    assert [message["task_type"] for message in sent_messages] == [
        "repository_sync",
        "project_profile",
    ]
    assert sent_messages[1]["project_id"] == project_id
    profile_response = client.get(f"/projects/{project_id}/profile")
    assert profile_response.status_code == 200
    assert profile_response.json()["status"] == "queued"


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
    (repo / "docs" / "admin.md").write_text(
        "# Admin domains\n\nAdmins can review domain audit history.\n",
        encoding="utf-8",
    )
    (repo / "src" / "domains.py").write_text(
        "def configure_domain(name: str) -> str:\n    return f'configured {name}'\n",
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
        },
    )

    assert index_response.status_code == 200
    index_run = index_response.json()
    assert index_run["status"] == "completed"
    assert index_run["summary"]["files"] == 2
    assert index_run["summary"]["documents"] == 2
    assert index_run["summary"]["sections"] == 2
    assert index_run["summary"]["nodes"] >= 3

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
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "repository-cache"))
    monkeypatch.chdir(tmp_path)
    repo = tmp_path / "source-repo"
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
    run_git(None, ["init", str(repo)])
    run_git(repo, ["config", "user.email", "test@example.com"])
    run_git(repo, ["config", "user.name", "GuideSync Test"])
    run_git(repo, ["add", "."])
    run_git(repo, ["commit", "-m", "Add knowledge fixture"])
    run_git(repo, ["branch", "-M", "main"])
    client = TestClient(app)
    project_response = client.post(
        "/projects",
        json={
            "name": "Knowledge project",
            "repositories": [
                {
                    "id": "repo-knowledge",
                    "name": "knowledge-repo",
                    "url": str(repo),
                    "default_branch": "main",
                    "paths": ["docs"],
                }
            ],
        },
    )
    project_id = project_response.json()["id"]

    index_response = client.post(
        f"/projects/{project_id}/knowledge/index-runs"
    )

    assert index_response.status_code == 200
    index_run = index_response.json()
    assert index_run["project_id"] == project_id
    assert index_run["status"] == "completed"
    assert index_run["summary"]["repositories"] == 1
    assert index_run["summary"]["files"] == 1
    assert index_run["summary"]["documents"] == 1
    assert index_run["summary"]["sections"] == 1
    assert index_run["summary"]["documentation_sources"] == 0
    assert index_run["summary"]["indexed_commit_sha"]
    assert index_run["summary"]["previous_indexed_commit_sha"] is None
    assert index_run["summary"]["changed_documentation_files"] == []
    assert index_run["summary"]["annotation_runs"] > 0
    assert index_run["summary"]["annotations"] > 0
    assert not any(
        "knowledge annotation failed" in warning for warning in index_run["summary"]["warnings"]
    )
    assert index_run["request"]["repositories"][0]["paths"] == ["docs/"]

    list_response = client.get(f"/projects/{project_id}/knowledge/index-runs")

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [index_run["id"]]

    search_response = client.post(
        "/knowledge/search",
        json={"project_id": project_id, "query": "terminal workflows", "limit": 5},
    )

    assert search_response.status_code == 200
    search_results = search_response.json()
    assert any(item["node"]["path"] == "docs/guide.md" for item in search_results)
    assert not any(item["node"]["path"] == "src/ignored.py" for item in search_results)

    document_response = client.get(f"/projects/{project_id}/knowledge/documents")
    tag_response = client.get(f"/projects/{project_id}/knowledge/tags")

    assert document_response.status_code == 200
    document_refs = document_response.json()
    assert document_refs["documents"][0]["path"] == "docs/guide.md"
    assert document_refs["documents"][0]["section_count"] == 1
    assert document_refs["sections"][0]["heading"] == "Terminal workflows"
    assert document_refs["sections"][0]["start_line"] == 1
    assert (
        document_refs["sections"][0]["source_commit"] == index_run["summary"]["indexed_commit_sha"]
    )
    assert document_refs["sections"][0]["keyphrases"]
    assert tag_response.status_code == 200
    assert any(item["value"] == "terminal" for item in tag_response.json())

    (repo / "docs" / "guide.md").write_text(
        "# Terminal workflows\n\nThe terminal panel supports command review and audit trails.\n",
        encoding="utf-8",
    )
    run_git(repo, ["add", "docs/guide.md"])
    run_git(repo, ["commit", "-m", "Update knowledge fixture"])

    second_index_response = client.post(
        f"/projects/{project_id}/knowledge/index-runs"
    )

    assert second_index_response.status_code == 200
    second_index_run = second_index_response.json()
    assert (
        second_index_run["summary"]["previous_indexed_commit_sha"]
        == index_run["summary"]["indexed_commit_sha"]
    )
    assert (
        second_index_run["summary"]["indexed_commit_sha"]
        != index_run["summary"]["indexed_commit_sha"]
    )
    assert second_index_run["summary"]["changed_documentation_files"] == ["docs/guide.md"]


def test_project_knowledge_index_can_use_repository_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'root-kg.db'}")
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "repository-cache"))
    monkeypatch.chdir(tmp_path)
    repo = tmp_path / "root-docs-repo"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# Root documentation\n\nDocker setup is documented at the repository root.\n",
        encoding="utf-8",
    )
    run_git(None, ["init", str(repo)])
    run_git(repo, ["config", "user.email", "test@example.com"])
    run_git(repo, ["config", "user.name", "GuideSync Test"])
    run_git(repo, ["add", "README.md"])
    run_git(repo, ["commit", "-m", "Add root README"])
    run_git(repo, ["branch", "-M", "main"])
    client = TestClient(app)
    project_response = client.post(
        "/projects",
        json={
            "name": "Root knowledge project",
            "knowledge_base_path": "",
            "repositories": [
                {
                    "id": "repo-root-knowledge",
                    "name": "root-knowledge-repo",
                    "url": str(repo),
                    "default_branch": "main",
                }
            ],
        },
    )
    project_id = project_response.json()["id"]

    index_response = client.post(
        f"/projects/{project_id}/knowledge/index-runs"
    )

    assert index_response.status_code == 200
    index_run = index_response.json()
    assert index_run["status"] == "completed"
    assert index_run["summary"]["files"] == 1
    assert index_run["summary"]["documents"] == 1
    assert index_run["summary"]["sections"] == 1
    assert index_run["summary"]["annotation_runs"] > 0
    assert not any(
        "knowledge annotation failed" in warning for warning in index_run["summary"]["warnings"]
    )
    assert index_run["request"]["repositories"][0]["paths"] == []

    search_response = client.post(
        "/knowledge/search",
        json={"project_id": project_id, "query": "docker setup", "limit": 5},
    )

    assert search_response.status_code == 200
    assert any(item["node"]["path"] == "README.md" for item in search_response.json())
