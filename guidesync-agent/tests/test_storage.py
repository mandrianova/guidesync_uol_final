from __future__ import annotations

from pathlib import Path

from guidesync_agent.schemas import (
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProjectCreate,
    ProjectDocumentation,
    ProjectRepository,
)
from guidesync_agent.storage import DatabaseProjectStore, DatabaseRunStore


def test_database_run_store_round_trip(tmp_path: Path) -> None:
    store = DatabaseRunStore(f"sqlite+pysqlite:///{tmp_path / 'runs.db'}")
    request = GuideSyncRunRequest.model_validate(
        {
            "run_id": "sqlite-round-trip",
            "goal": "Store a run result.",
            "repositories": [
                {
                    "name": "repo",
                    "path": ".",
                }
            ],
        }
    )
    result = GuideSyncRunResult(
        run_id=request.run_id,
        status="completed",
        request=request,
        evidence=EvidenceBundle(repositories=["."]),
    )

    store.save(result)
    loaded = store.get("sqlite-round-trip")

    assert loaded is not None
    assert loaded.run_id == "sqlite-round-trip"
    assert loaded.status == "completed"

    summaries = store.list_runs()

    assert len(summaries) == 1
    assert summaries[0].run_id == "sqlite-round-trip"
    assert summaries[0].title == "GuideSync documentation update"


def test_database_project_store_round_trip(tmp_path: Path) -> None:
    store = DatabaseProjectStore(f"sqlite+pysqlite:///{tmp_path / 'projects.db'}")
    project = ProjectCreate(
        name="Docs project",
        repositories=[
            ProjectRepository(
                id="repo-primary",
                name="public-repo",
                url="https://github.com/example/public-repo",
                default_branch="main",
                paths=["docs/"],
            )
        ],
        documentation=[
            ProjectDocumentation(
                id="doc-primary",
                name="docs-context",
                content="Stored documentation context.",
            )
        ],
    )

    saved = store.save(project)
    loaded = store.get(saved.id)

    assert loaded is not None
    assert loaded.name == "Docs project"
    assert loaded.repositories[0].url == "https://github.com/example/public-repo"
    assert loaded.documentation[0].content == "Stored documentation context."
