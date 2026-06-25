from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect, select

from guidesync_agent.knowledge import build_knowledge_snapshot
from guidesync_agent.schemas import (
    Audience,
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    KnowledgeIndexRequest,
    ModelSettingsUpdate,
    ProjectCreate,
    ProjectDocumentation,
    ProjectProfileRepositoryMapItem,
    ProjectProfileSnapshot,
    ProjectProfileSourceRef,
    ProjectProfileStatus,
    ProjectRepository,
    ProviderKind,
    RepositoryCacheStatus,
    RepositoryInput,
    ScreenshotPolicy,
)
from guidesync_agent.storage import (
    DatabaseKnowledgeStore,
    DatabaseModelSettingsStore,
    DatabaseProjectProfileStore,
    DatabaseProjectStore,
    DatabaseRunStore,
)
from guidesync_agent.storage_schema import (
    knowledge_chunks_table,
    project_documentation_table,
    report_runs_table,
)


def test_database_run_store_round_trip(tmp_path: Path) -> None:
    store = DatabaseRunStore(f"sqlite+pysqlite:///{tmp_path / 'runs.db'}")
    request = GuideSyncRunRequest.model_validate(
        {
            "run_id": "sqlite-round-trip",
            "goal": "Store a run result.",
            "audience": "business_analysts",
            "task_interface_url": "http://127.0.0.1:5173/#/run",
            "screenshot_policy": "required",
            "requested_model_settings": {
                "model_profile_id": "model-local",
                "provider": "local_http",
                "model": "google/gemma-4-31b-qat",
                "timeout_seconds": 120,
                "thinking": "medium",
            },
            "effective_model_configuration": {
                "model_profile_id": "model-local",
                "name": "Local Gemma",
                "provider": "local_http",
                "model": "google/gemma-4-31b-qat",
                "base_url": "http://localhost:1234/v1",
                "timeout_seconds": 120,
                "thinking": "medium",
            },
            "project_profile_snapshot_id": "profile-snapshot-1",
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
    assert loaded.request.audience == Audience.BUSINESS_ANALYSTS
    assert loaded.request.screenshot_policy == ScreenshotPolicy.REQUIRED
    assert loaded.request.requested_model_settings is not None
    assert loaded.request.requested_model_settings.model_profile_id == "model-local"
    assert loaded.request.effective_model_configuration is not None
    assert loaded.request.effective_model_configuration.model == "google/gemma-4-31b-qat"
    assert loaded.request.project_profile_snapshot_id == "profile-snapshot-1"

    with store.engine.begin() as connection:
        row = connection.execute(
            select(report_runs_table).where(report_runs_table.c.id == "sqlite-round-trip")
        ).one()

    assert row.screenshot_policy == "required"
    assert row.requested_model_settings["model_profile_id"] == "model-local"
    assert row.effective_model_configuration["provider"] == "local_http"

    summaries = store.list_runs()

    assert len(summaries) == 1
    assert summaries[0].run_id == "sqlite-round-trip"
    assert summaries[0].title == "GuideSync release notes"


def test_database_project_store_round_trip(tmp_path: Path) -> None:
    store = DatabaseProjectStore(f"sqlite+pysqlite:///{tmp_path / 'projects.db'}")
    project = ProjectCreate(
        name="Docs project",
        audience=Audience.DEVELOPERS,
        documentation_instructions="Keep developer docs concise and traceable.",
        knowledge_base_repository_id="repo-primary",
        knowledge_base_ref="main",
        knowledge_base_path="docs/",
        analysis_paths=["src/", "docs/"],
        credential_ref="credential-project",
        repositories=[
            ProjectRepository(
                id="repo-primary",
                name="public-repo",
                url="https://github.com/example/public-repo",
                default_branch="main",
                analysis_paths=["src/", "docs/"],
                credential_ref="credential-repo",
                cache_status=RepositoryCacheStatus.READY,
                local_path="/tmp/guidesync/repo-primary",
                current_commit="abc123",
                cache_warnings=["stale by 1 commit"],
            )
        ],
        documentation=[
            ProjectDocumentation(
                id="doc-primary",
                name="docs-context",
                path="docs/guide.md",
            )
        ],
    )

    saved = store.save(project)
    loaded = store.get(saved.id)

    assert loaded is not None
    assert loaded.name == "Docs project"
    assert loaded.audience == Audience.DEVELOPERS
    assert loaded.documentation_instructions == "Keep developer docs concise and traceable."
    assert loaded.knowledge_base_repository_id == "repo-primary"
    assert loaded.knowledge_base_ref == "main"
    assert loaded.knowledge_base_path == "docs/"
    assert loaded.analysis_paths == ["src/", "docs/"]
    assert loaded.credential_ref == "credential-project"
    assert loaded.repositories[0].url == "https://github.com/example/public-repo"
    assert loaded.repositories[0].analysis_paths == ["src/", "docs/"]
    assert loaded.repositories[0].paths == ["src/", "docs/"]
    assert loaded.repositories[0].credential_ref == "credential-repo"
    assert loaded.repositories[0].cache_status == "ready"
    assert loaded.repositories[0].local_path == "/tmp/guidesync/repo-primary"
    assert loaded.repositories[0].current_commit == "abc123"
    assert loaded.repositories[0].cache_warnings == ["stale by 1 commit"]
    assert loaded.documentation[0].path == "docs/guide.md"


def test_database_project_profile_store_round_trip(tmp_path: Path) -> None:
    store = DatabaseProjectProfileStore(f"sqlite+pysqlite:///{tmp_path / 'profiles.db'}")
    profile = ProjectProfileSnapshot(
        id="profile-round-trip",
        project_id="project-round-trip",
        status=ProjectProfileStatus.COMPLETED,
        version=2,
        prompt_version="project-profile-analyzer-v1",
        summary="GuideSync keeps documentation updates grounded in repository evidence.",
        architecture=["Repository evidence pipeline", "Documentation update workflow"],
        workflows=["Create project", "Run analysis", "Review report"],
        key_terms=["guidesync", "documentation", "evidence"],
        repository_map=[
            ProjectProfileRepositoryMapItem(
                repository_id="repo-primary",
                name="primary",
                url="https://github.com/example/repo",
                default_branch="main",
                current_commit="abc123",
                cache_status=RepositoryCacheStatus.READY,
                analysis_paths=["src/", "docs/"],
                knowledge_base_path="docs/",
            )
        ],
        source_refs=[
            ProjectProfileSourceRef(
                repository_id="repo-primary",
                repository_name="primary",
                ref="main",
                commit_sha="abc123",
                local_path="/tmp/repo",
                docs_path="docs/",
                analysis_paths=["src/", "docs/"],
            )
        ],
        warnings=["stale cache"],
        uncertainty_notes=["Review generated profile before use."],
        artifact_uris={"profile.md": "/tmp/profile.md"},
    )

    store.save(profile)
    loaded = store.get("profile-round-trip")
    latest = store.latest("project-round-trip")

    assert loaded is not None
    assert loaded.status == ProjectProfileStatus.COMPLETED
    assert loaded.version == 2
    assert loaded.repository_map[0].cache_status == RepositoryCacheStatus.READY
    assert loaded.source_refs[0].docs_path == "docs/"
    assert latest is not None
    assert latest.id == "profile-round-trip"


def test_database_knowledge_store_does_not_store_full_document_body(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    full_body = (
        "# Operations guide\n\n"
        "This short summary is searchable.\n\n"
        "Do not persist this exact long implementation detail in chunk text.\n"
    )
    (repo / "docs" / "guide.md").write_text(full_body, encoding="utf-8")
    store = DatabaseKnowledgeStore(f"sqlite+pysqlite:///{tmp_path / 'knowledge.db'}")
    snapshot = build_knowledge_snapshot(
        KnowledgeIndexRequest(
            repositories=[
                RepositoryInput(name="fixture", path=repo, paths=["docs"]),
            ]
        )
    )

    store.save_snapshot(snapshot)

    with store.engine.begin() as connection:
        chunk_texts = [
            row.text for row in connection.execute(select(knowledge_chunks_table.c.text)).all()
        ]

    assert chunk_texts
    assert full_body not in chunk_texts
    assert all(
        "Do not persist this exact long implementation detail" not in text
        for text in chunk_texts
    )


def test_project_audience_rejects_legacy_free_text_values() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate.model_validate({"name": "Bad project", "audience": "product users"})

    with pytest.raises(ValidationError):
        GuideSyncRunRequest.model_validate(
            {
                "goal": "Reject legacy audience.",
                "audience": "documentation reviewer",
                "repositories": [{"name": "repo", "path": "."}],
            }
        )


def test_database_project_store_does_not_store_documentation_content(tmp_path: Path) -> None:
    store = DatabaseProjectStore(f"sqlite+pysqlite:///{tmp_path / 'no-doc-content.db'}")
    project = ProjectCreate.model_validate(
        {
            "name": "No stored docs body",
            "documentation": [
                {
                    "id": "doc-legacy",
                    "name": "legacy-context",
                    "description": "Legacy clients may still send this.",
                    "content": "This full documentation body must not be stored.",
                }
            ],
        }
    )

    saved = store.save(project)
    loaded = store.get(saved.id)

    assert loaded is not None
    assert "content" not in loaded.documentation[0].model_dump()

    columns = {
        column["name"]
        for column in inspect(store.engine).get_columns("guidesync_project_documentation")
    }
    assert "content" not in columns

    with store.engine.begin() as connection:
        row = connection.execute(select(project_documentation_table)).one()

    assert "content" not in row._mapping
    assert row.path is None


def test_database_model_settings_store_keeps_api_key_server_side(tmp_path: Path) -> None:
    store = DatabaseModelSettingsStore(f"sqlite+pysqlite:///{tmp_path / 'settings.db'}")

    saved = store.save(
        ModelSettingsUpdate(
            provider=ProviderKind.PYDANTIC_AI,
            model="openai:gpt-4.1",
            base_url=None,
            api_key="secret-token",
            timeout_seconds=120,
            thinking="high",
        )
    )
    public_dump = saved.model_dump(mode="json")
    provider_config = store.provider_config()

    assert saved.has_api_key is True
    assert "api_key" not in public_dump
    assert provider_config.api_key == "secret-token"
    assert provider_config.model == "openai:gpt-4.1"
    assert provider_config.timeout_seconds == 120
    assert provider_config.thinking == "high"


def test_database_model_settings_store_manages_profiles(tmp_path: Path) -> None:
    store = DatabaseModelSettingsStore(f"sqlite+pysqlite:///{tmp_path / 'profiles.db'}")
    original = store.get()
    added = store.save_profile(
        ModelSettingsUpdate(
            name="Anthropic review",
            provider=ProviderKind.PYDANTIC_AI,
            model="anthropic:claude-3-5-sonnet-latest",
            api_key="anthropic-token",
            timeout_seconds=90,
            thinking="medium",
        )
    )

    profiles = store.list_profiles()

    assert {profile.id for profile in profiles} == {original.id, added.id}
    assert next(profile for profile in profiles if profile.id == original.id).is_default is True
    assert added.is_default is False
    assert added.timeout_seconds == 90
    assert added.thinking == "medium"

    selected = store.set_default(added.id)

    assert selected is not None
    assert selected.id == added.id
    assert store.provider_config().model == "anthropic:claude-3-5-sonnet-latest"
    assert store.provider_config().api_key == "anthropic-token"
    assert store.provider_config().timeout_seconds == 90
    assert store.provider_config().thinking == "medium"

    deleted_default = store.delete_profile(added.id)

    assert deleted_default is None

    deleted_original = store.delete_profile(original.id)

    assert deleted_original is None
    assert {profile.id for profile in store.list_profiles()} == {original.id, added.id}
