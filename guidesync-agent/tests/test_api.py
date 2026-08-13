from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from storage_test_utils import sqlite_database_url

from guidesync_agent.api import app
from guidesync_agent.reports import read_artifact
from guidesync_agent.schemas import (
    VideoPresentationPolicy,
    VideoPresentationStatus,
    VideoPresentationSummary,
)
from guidesync_agent.services.workflows.executor import ProjectWorkflowExecutor
from guidesync_agent.storage import DatabaseRunStore

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


def drain_project_workflow() -> None:
    executor = ProjectWorkflowExecutor()
    while task := executor.claim_next_task():
        asyncio.run(executor.execute(task))


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


def test_manual_video_command_uses_typed_post_publication_contract(monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []

    def enqueue(run_id: str, *, regenerate: bool = False) -> VideoPresentationSummary:
        calls.append((run_id, regenerate))
        return VideoPresentationSummary(
            policy=VideoPresentationPolicy.OPTIONAL,
            status=VideoPresentationStatus.QUEUED,
            workflow_task_id="workflow-video-1",
        )

    monkeypatch.setattr(
        "guidesync_agent.controllers.runs.enqueue_video_presentation",
        enqueue,
    )
    response = TestClient(app).post(
        "/runs/project-test-run/video-presentation",
        json={"regenerate": True},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert calls == [("project-test-run", True)]


def test_create_and_get_run(tmp_path: Path) -> None:
    client = TestClient(app)

    create_response = client.post("/runs", json=load_fixture(tmp_path))

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["run_id"] == "pytest-api-domain-guide"
    assert created["status"] == "completed"
    assert created["update"]["title"] == "Custom domain management updates"
    report_uri = created["artifacts"]["report.json"]
    assert report_uri.startswith("s3://")
    assert report_uri.endswith("/tests/pytest-api-domain-guide/report.json")
    assert read_artifact(report_uri).body

    get_response = client.get("/runs/pytest-api-domain-guide")

    assert get_response.status_code == 200
    assert get_response.json()["run_id"] == "pytest-api-domain-guide"

    list_response = client.get("/runs")

    assert list_response.status_code == 200
    assert any(item["run_id"] == "pytest-api-domain-guide" for item in list_response.json())

    markdown_response = client.get(
        "/runs/pytest-api-domain-guide/artifacts/technical-report.md"
    )

    assert markdown_response.status_code == 200
    assert "text/markdown" in markdown_response.headers["content-type"]
    assert markdown_response.headers["content-disposition"] == (
        'attachment; filename="technical-report.md"'
    )
    assert "# GuideSync domain release notes" in markdown_response.text

    publication_response = client.get(
        "/runs/pytest-api-domain-guide/publication-report"
    )

    assert publication_response.status_code == 200
    publication = publication_response.json()
    assert publication["title"] == "GuideSync domain release notes"
    assert publication["changes"][0]["title"] == "Custom domain management updates"
    assert "provider_metadata" not in publication

    assert client.get("/runs/pytest-api-domain-guide/artifacts/report.html").status_code == 404
    assert client.get("/runs/pytest-api-domain-guide/artifacts/report.pdf").status_code == 404


def test_project_run_is_created_as_tracked_task(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "runs.db"))
    monkeypatch.setenv("GUIDESYNC_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("GUIDESYNC_AGENT_MODEL", "mock:deterministic")
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
                    "analysis_paths": [],
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
            "max_commits": 1,
        },
    )

    assert run_response.status_code == 200
    created = run_response.json()
    assert created["run_id"].startswith(f"{project_id}-")
    assert created["status"] == "planning"
    assert created["created_at"]

    get_response = client.get(f"/runs/{created['run_id']}")

    assert get_response.status_code == 200
    created_request = get_response.json()["request"]
    assert created_request["provider"]["provider"] == "mock"
    assert created_request["report"]["locale"] == "en"
    assert created_request["repositories"][0]["max_commits"] == 1
    workflow_response = client.get(f"/projects/{project_id}/workflow/tasks")
    assert workflow_response.status_code == 200
    assert [task["kind"] for task in workflow_response.json()] == [
        "repository_sync",
        "project_profile",
        "knowledge_index",
        "change_analysis_plan",
    ]

    list_response = client.get(f"/projects/{project_id}/runs")

    assert list_response.status_code == 200
    assert any(item["run_id"] == created["run_id"] for item in list_response.json())

    cancel_response = client.post(f"/runs/{created['run_id']}/cancel")

    assert cancel_response.status_code == 200
    assert cancel_response.json()["run"]["status"] == "cancelled"
    assert cancel_response.json()["cancelled_task_ids"]
    assert client.get(f"/runs/{created['run_id']}").json()["status"] == "cancelled"


def test_project_workflow_task_can_be_cancelled(monkeypatch, tmp_path: Path) -> None:
    database_url = sqlite_database_url(tmp_path / "cancel-workflow-task-api.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    client = TestClient(app)
    project = client.post("/projects", json={"name": "Cancelable profile"}).json()
    plan_response = client.post(f"/projects/{project['id']}/workflow/profile")
    assert plan_response.status_code == 200
    task_id = plan_response.json()["tasks"][-1]["id"]

    response = client.post(
        f"/projects/{project['id']}/workflow/tasks/{task_id}/cancel"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["progress"]["stage"] == "cancelled"
    assert client.post(
        f"/projects/{project['id']}/workflow/tasks/{task_id}/cancel"
    ).status_code == 409
    assert client.post(
        f"/projects/another-project/workflow/tasks/{task_id}/cancel"
    ).status_code == 404


@pytest.mark.parametrize("terminal_status", ["failed", "cancelled"])
def test_terminal_project_run_can_be_retried_as_new_run(
    monkeypatch,
    tmp_path: Path,
    terminal_status: str,
) -> None:
    database_url = sqlite_database_url(tmp_path / f"retry-{terminal_status}-api.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setenv("GUIDESYNC_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("GUIDESYNC_AGENT_MODEL", "mock:deterministic")
    client = TestClient(app)
    project = client.post(
        "/projects",
        json={
            "name": "Retry API project",
            "repositories": [
                {
                    "id": "repo-retry-api",
                    "name": "repo",
                    "url": "https://github.com/example/repo",
                    "default_branch": "main",
                }
            ],
        },
    ).json()
    original_summary = client.post(
        f"/projects/{project['id']}/runs",
        json={"goal": "Retry this failed report."},
    ).json()
    run_store = DatabaseRunStore(database_url)
    original = run_store.get(original_summary["run_id"])
    assert original is not None
    run_store.save(original.model_copy(update={"status": terminal_status}))

    response = client.post(f"/runs/{original.run_id}/retry")

    assert response.status_code == 202
    plan = response.json()
    assert plan["run"]["run_id"] != original.run_id
    assert plan["run"]["status"] == "planning"
    retried = client.get(f"/runs/{plan['run']['run_id']}").json()
    assert retried["request"]["retry_of_run_id"] == original.run_id
    assert client.get(f"/runs/{original.run_id}").json()["status"] == terminal_status
    assert client.post(f"/runs/{plan['run']['run_id']}/retry").status_code == 409
    assert client.post("/runs/missing-run/retry").status_code == 404


def test_project_run_rejects_non_english_report_locale(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "locale.db"))
    client = TestClient(app)
    project = client.post("/projects", json={"name": "English reports project"}).json()

    response = client.post(
        f"/projects/{project['id']}/runs",
        json={
            "goal": "Create a non-English report task.",
            "report_locale": "ru",
        },
    )

    assert response.status_code == 422


def test_project_run_uses_environment_provider_when_request_provider_is_omitted(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "providers.db"))
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
                    "analysis_paths": [],
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


def test_project_run_rejects_model_override_and_stores_effective_model_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "run-model.db"))
    monkeypatch.setenv("GUIDESYNC_AGENT_PROVIDER", "local_http")
    monkeypatch.setenv("GUIDESYNC_AGENT_MODEL", "google/gemma-4-31b-qat")
    monkeypatch.setenv("GUIDESYNC_AGENT_BASE_URL", "http://localhost:1234/api/v1/chat")
    monkeypatch.setenv("GUIDESYNC_AGENT_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("GUIDESYNC_AGENT_THINKING", "medium")
    client = TestClient(app)
    project_response = client.post(
        "/projects",
        json={
            "name": "Run model project",
            "task_interface_url": "http://127.0.0.1:5173/#/project-default",
            "repositories": [
                {
                    "id": "repo-run-model",
                    "name": "repo",
                    "url": "https://github.com/example/repo",
                    "default_branch": "main",
                    "analysis_paths": [],
                }
            ],
        },
    )
    project_id = project_response.json()["id"]

    rejected_response = client.post(
        f"/projects/{project_id}/runs",
        json={
            "goal": "Create a model snapshot report task.",
            "mode": "default_branch_period",
            "since": "2026-06-01",
            "until": None,
            "branches": {},
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

    assert rejected_response.status_code == 422

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
        },
    )

    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]
    request = client.get(f"/runs/{run_id}").json()["request"]

    assert request["task_interface_url"] == "http://127.0.0.1:5173/#/run"
    assert request["screenshot_policy"] == "required"
    assert "requested_model_settings" not in request
    assert request["effective_model_configuration"]["provider"] == "local_http"
    assert request["effective_model_configuration"]["model"] == "google/gemma-4-31b-qat"
    assert request["effective_model_configuration"]["timeout_seconds"] == 120
    assert request["effective_model_configuration"]["max_concurrent_agents"] == 1
    assert request["effective_model_configuration"]["thinking"] == "medium"

    inherited_response = client.post(
        f"/projects/{project_id}/runs",
        json={
            "goal": "Use the project UI URL.",
            "screenshot_policy": "optional",
        },
    )

    assert inherited_response.status_code == 200
    inherited_request = client.get(
        f"/runs/{inherited_response.json()['run_id']}"
    ).json()["request"]
    assert inherited_request["task_interface_url"] == (
        "http://127.0.0.1:5173/#/project-default"
    )
    assert inherited_request["screenshot_policy"] == "optional"


def test_project_and_run_ui_auth_cookie_is_write_only(monkeypatch, tmp_path: Path) -> None:
    database_url = sqlite_database_url(tmp_path / "ui-auth-cookie.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    client = TestClient(app)
    project_payload = {
        "name": "Authenticated UI project",
        "task_interface_url": "https://product.example.com/private",
        "task_interface_auth_cookie_update": "replace",
        "task_interface_auth_cookie": "session=project-secret",
        "repositories": [
            {
                "id": "repo-auth-ui",
                "name": "repo",
                "url": "https://github.com/example/repo",
                "default_branch": "main",
            }
        ],
    }

    created_response = client.post("/projects", json=project_payload)

    assert created_response.status_code == 200
    project = created_response.json()
    assert project["has_task_interface_auth_cookie"] is True
    assert "task_interface_auth_cookie" not in project
    assert "project-secret" not in created_response.text

    run_response = client.post(
        f"/projects/{project['id']}/runs",
        json={
            "goal": "Capture the authenticated UI.",
            "screenshot_policy": "optional",
            "task_interface_auth_cookie_mode": "inherit",
        },
    )
    assert run_response.status_code == 200
    run_request = client.get(f"/runs/{run_response.json()['run_id']}").json()["request"]
    assert run_request["task_interface_auth_cookie_mode"] == "inherit"
    assert run_request["has_task_interface_auth_cookie"] is True
    assert "task_interface_auth_cookie" not in run_request

    override_response = client.post(
        f"/projects/{project['id']}/runs",
        json={
            "goal": "Capture with a one-run cookie.",
            "screenshot_policy": "optional",
            "task_interface_auth_cookie_mode": "override",
            "task_interface_auth_cookie": "session=run-secret",
        },
    )
    assert override_response.status_code == 200
    override_get = client.get(f"/runs/{override_response.json()['run_id']}")
    assert override_get.json()["request"]["has_task_interface_auth_cookie"] is True
    assert "run-secret" not in override_get.text

    disabled_response = client.post(
        f"/projects/{project['id']}/runs",
        json={
            "goal": "Capture without project authorization.",
            "screenshot_policy": "optional",
            "task_interface_auth_cookie_mode": "disabled",
        },
    )
    assert disabled_response.status_code == 200
    disabled_request = client.get(
        f"/runs/{disabled_response.json()['run_id']}"
    ).json()["request"]
    assert disabled_request["task_interface_auth_cookie_mode"] == "disabled"
    assert disabled_request["has_task_interface_auth_cookie"] is False

    removed_response = client.put(
        f"/projects/{project['id']}",
        json={
            **project_payload,
            "task_interface_auth_cookie_update": "remove",
            "task_interface_auth_cookie": None,
        },
    )
    assert removed_response.status_code == 200
    assert removed_response.json()["has_task_interface_auth_cookie"] is False
    assert "task_interface_auth_cookie" not in removed_response.json()


def test_project_profile_builds_after_project_create_and_update(  # noqa: PLR0915
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "profiles.db"))
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
    drain_project_workflow()

    profile_response = client.get(f"/projects/{project_id}/profile")

    assert profile_response.status_code == 200
    profile = profile_response.json()
    assert profile["status"] == "completed"
    assert profile["version"] == 1
    assert profile["summary"]
    assert any("System architecture" in item for item in profile["architecture"])
    assert "Release notes" in profile["taxonomy"]["categories"]
    assert profile["workflows"] == []
    assert profile["key_terms"] == []
    assert profile["repository_map"][0]["repository_id"] == "repo-profile"
    assert profile["source_refs"][0]["commit_sha"]
    assert profile["model_metadata"]["provider"] == "pydantic_ai"
    assert profile["tool_trace_refs"]
    assert profile["validation_findings"] == []
    assert Path(profile["artifact_uris"]["profile.json"]).exists()
    assert "## Documentation categories" in Path(profile["artifact_uris"]["profile.md"]).read_text(
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
    drain_project_workflow()
    rebuilt_profile = client.get(f"/projects/{project_id}/profile").json()
    assert rebuilt_profile["version"] == 2
    assert rebuilt_profile["status"] == "completed"


def test_project_create_uses_durable_workflow_when_sqs_is_enabled(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "queued.db"))
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_SYNC_QUEUE_URL", "http://queue.example/test")
    sent_messages = []

    class FakeSqs:
        def send_message(
            self,
            *,
            QueueUrl: str,  # noqa: N803 - mirrors boto3 keyword arguments
            MessageBody: str,  # noqa: N803 - mirrors boto3 keyword arguments
        ) -> dict[str, str]:
            sent_messages.append(json.loads(MessageBody))
            return {"MessageId": f"message-{len(sent_messages)}"}

    monkeypatch.setattr(
        "guidesync_agent.services.repositories.tasks.boto3.client",
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
    assert sent_messages == []
    workflow_response = client.get(f"/projects/{project_id}/workflow/tasks")
    assert workflow_response.status_code == 200
    assert [task["kind"] for task in workflow_response.json()] == [
        "repository_sync",
        "project_profile",
    ]
    profile_response = client.get(f"/projects/{project_id}/profile")
    assert profile_response.status_code == 404


def test_built_in_default_model_is_read_only(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "models.db"))
    client = TestClient(app)

    profiles_response = client.get("/settings/models")

    assert profiles_response.status_code == 200
    default_profile = profiles_response.json()[0]
    assert default_profile["id"] == "global-default"
    assert default_profile["max_concurrent_agents"] == 1

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


def test_model_profile_agent_concurrency_round_trips_through_api(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "models.db"))
    client = TestClient(app)

    create_response = client.post(
        "/settings/models",
        json={
            "name": "Hosted analysis",
            "provider": "pydantic_ai",
            "model": "openai:gpt-5.4-mini",
            "timeout_seconds": 120,
            "max_concurrent_agents": 3,
        },
    )

    assert create_response.status_code == 200
    profile = create_response.json()
    assert profile["max_concurrent_agents"] == 3

    update_response = client.put(
        f"/settings/models/{profile['id']}",
        json={
            "name": "Hosted analysis",
            "provider": "pydantic_ai",
            "model": "openai:gpt-5.4-mini",
            "timeout_seconds": 120,
            "max_concurrent_agents": 2,
        },
    )
    invalid_response = client.put(
        f"/settings/models/{profile['id']}",
        json={
            "name": "Hosted analysis",
            "provider": "pydantic_ai",
            "model": "openai:gpt-5.4-mini",
            "timeout_seconds": 120,
            "max_concurrent_agents": 0,
        },
    )

    assert update_response.status_code == 200
    assert update_response.json()["max_concurrent_agents"] == 2
    assert invalid_response.status_code == 422


def test_knowledge_index_search_and_context_pack(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "knowledge.db"))
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


def test_project_knowledge_index_uses_saved_project_repositories(  # noqa: PLR0915
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "project-kg.db"))
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
                    "analysis_paths": ["docs"],
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
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "root-kg.db"))
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
