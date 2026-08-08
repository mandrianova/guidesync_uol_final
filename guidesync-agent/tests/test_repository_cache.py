from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from storage_test_utils import sqlite_database_url

from guidesync_agent import evidence as evidence_module
from guidesync_agent.api import app
from guidesync_agent.controllers import repositories as repository_controller
from guidesync_agent.evidence import collect_repository_evidence
from guidesync_agent.schemas import (
    ProjectRepository,
    RepositoryCacheStatus,
    RepositoryInput,
    RepositorySyncTask,
)
from guidesync_agent.services.repository_cache import RepositoryCacheService


def run_git(repo: Path | None, args: list[str]) -> None:
    command = ["git", *args] if repo is None else ["git", "-C", str(repo), *args]
    subprocess.run(command, check=True, capture_output=True, text=True)


def create_source_repository(tmp_path: Path) -> Path:
    source = tmp_path / "source-repo"
    (source / "docs").mkdir(parents=True)
    (source / "src").mkdir()
    (source / "docs" / "guide.md").write_text("# Guide\n\nInitial docs.\n", encoding="utf-8")
    (source / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    run_git(None, ["init", str(source)])
    run_git(source, ["config", "user.email", "test@example.com"])
    run_git(source, ["config", "user.name", "GuideSync Test"])
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Add initial docs"])
    run_git(source, ["branch", "-M", "main"])
    run_git(source, ["checkout", "-b", "docs-update"])
    (source / "docs" / "guide.md").write_text(
        "# Guide\n\nInitial docs.\n\nDocument the branch flow.\n",
        encoding="utf-8",
    )
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Update docs guide"])
    run_git(source, ["checkout", "main"])
    return source


def test_repository_cache_lists_branches_from_any_clone_url(tmp_path: Path) -> None:
    source = create_source_repository(tmp_path)
    service = RepositoryCacheService(tmp_path / "cache")
    repository = ProjectRepository(
        id="repo-primary",
        name="fixture",
        url=str(source),
        default_branch="main",
        analysis_paths=["docs"],
    )

    updated, branches, warning = service.list_branches("project-primary", repository)

    assert warning is None
    assert updated.cache_status == RepositoryCacheStatus.READY
    assert updated.local_path is not None
    assert Path(updated.local_path).parent.name.startswith("project-primary")
    assert Path(updated.local_path).name.startswith("repo-primary")
    assert (Path(updated.local_path) / "docs" / "guide.md").exists()
    assert updated.current_commit
    assert {branch.name for branch in branches} == {"docs-update", "main"}


def test_collect_repository_evidence_uses_local_cache_for_non_github_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = create_source_repository(tmp_path)
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "repository-cache"))

    commits, warnings = collect_repository_evidence(
        RepositoryInput(
            name="fixture",
            project_id="project-evidence",
            repository_id="repo-evidence",
            url=str(source),
            since=None,
            branches=["main"],
            paths=["docs"],
        )
    )

    assert warnings == []
    assert [commit.subject for commit in commits] == ["Add initial docs"]


def test_commit_collection_keeps_partial_evidence_when_blob_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = create_source_repository(tmp_path)

    def missing_stats(_repo: Path, _sha: str, _paths: list[str]) -> list[object]:
        raise subprocess.CalledProcessError(
            128,
            ["git", "show"],
            stderr="missing promised blob",
        )

    monkeypatch.setattr(evidence_module, "collect_file_stats", missing_stats)

    commits, warnings = collect_repository_evidence(
        RepositoryInput(
            name="fixture",
            path=source,
            ref="main",
            paths=["docs"],
        )
    )

    assert [commit.subject for commit in commits] == ["Add initial docs"]
    assert commits[0].file_stats == []
    assert warnings == [
        f"fixture: file stats unavailable for {commits[0].short_sha}: missing promised blob"
    ]


def test_project_repository_branches_endpoint_updates_cache_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = create_source_repository(tmp_path)
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "api.db"))
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "repository-cache"))
    client = TestClient(app)
    project_response = client.post(
        "/projects",
        json={
            "name": "Repository cache API",
            "repositories": [
                {
                    "id": "repo-api",
                    "name": "fixture",
                    "url": str(source),
                    "default_branch": "main",
                    "paths": ["docs"],
                }
            ],
        },
    )
    project_id = project_response.json()["id"]

    branches_response = client.get(f"/projects/{project_id}/repositories/repo-api/branches")
    project_reload_response = client.get(f"/projects/{project_id}")

    assert branches_response.status_code == 200
    assert branches_response.json()["warning"] is None
    assert {branch["name"] for branch in branches_response.json()["branches"]} == {
        "docs-update",
        "main",
    }
    repository = project_reload_response.json()["repositories"][0]
    assert repository["cache_status"] == "ready"
    assert repository["local_path"]
    assert repository["current_commit"]


def test_project_create_queues_repository_sync_when_sqs_is_configured(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class RecordingQueue:
        enabled = True

        def __init__(self) -> None:
            self.tasks: list[RepositorySyncTask] = []

        def send_repository_sync(self, task: RepositorySyncTask) -> bool:
            self.tasks.append(task)
            return True

    queue = RecordingQueue()
    source = create_source_repository(tmp_path)
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "queue.db"))
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "repository-cache"))
    monkeypatch.setattr(repository_controller, "RepositoryTaskQueue", lambda: queue)
    client = TestClient(app)

    project_response = client.post(
        "/projects",
        json={
            "name": "Queued repository project",
            "repositories": [
                {
                    "id": "repo-queued",
                    "name": "fixture",
                    "url": str(source),
                    "default_branch": "main",
                    "paths": ["docs"],
                }
            ],
        },
    )

    assert project_response.status_code == 200
    repository = project_response.json()["repositories"][0]
    assert repository["cache_status"] == "syncing"
    assert repository["local_path"]
    assert queue.tasks == [
        RepositorySyncTask(
            project_id=project_response.json()["id"],
            repository_id="repo-queued",
        )
    ]

    project_payload = project_response.json()
    project_payload["description"] = "Only documentation settings changed."
    update_response = client.put(
        f"/projects/{project_payload['id']}",
        json={
            "name": project_payload["name"],
            "description": project_payload["description"],
            "audience": project_payload["audience"],
            "documentation_instructions": project_payload["documentation_instructions"],
            "knowledge_base_repository_id": project_payload["knowledge_base_repository_id"],
            "knowledge_base_ref": project_payload["knowledge_base_ref"],
            "knowledge_base_path": project_payload["knowledge_base_path"],
            "analysis_paths": project_payload["analysis_paths"],
            "credential_ref": project_payload["credential_ref"],
            "repositories": project_payload["repositories"],
            "documentation": project_payload["documentation"],
        },
    )

    assert update_response.status_code == 200
    assert len(queue.tasks) == 1
