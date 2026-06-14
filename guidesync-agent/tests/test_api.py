from __future__ import annotations

import json
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
    assert created["update"]["title"] == "Custom domain guide update"
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
    assert "# Custom domain guide" in markdown_response.text

    print_response = client.get("/runs/pytest-api-domain-guide/artifacts/report.html?print=1")

    assert print_response.status_code == 200
    assert "text/html" in print_response.headers["content-type"]
    assert "GuideSync documentation report" in print_response.text
    assert "<pre>" not in print_response.text
    assert "window.print()" in print_response.text


def test_project_run_is_created_as_tracked_task() -> None:
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
                    "content": "Documentation context.",
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
) -> None:
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
                    "content": "Documentation context.",
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
