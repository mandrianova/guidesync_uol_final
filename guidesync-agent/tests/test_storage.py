from __future__ import annotations

import json
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection

import pytest
from pydantic import ValidationError
from sqlalchemy import event, inspect, select

from guidesync_agent import storage_schema
from guidesync_agent.knowledge import build_knowledge_snapshot
from guidesync_agent.models import (
    knowledge_annotation_edges_table,
    knowledge_annotation_runs_table,
    knowledge_annotations_table,
    knowledge_chunks_table,
    knowledge_concepts_table,
    project_documentation_table,
    report_runs_table,
)
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
    ProjectTaxonomy,
    ProviderKind,
    RepositoryCacheStatus,
    RepositoryInput,
    ScreenshotPolicy,
    ValidationFinding,
)
from guidesync_agent.storage import (
    DatabaseKnowledgeStore,
    DatabaseModelSettingsStore,
    DatabaseProjectProfileStore,
    DatabaseProjectStore,
    DatabaseRunStore,
    FileKnowledgeStore,
    FileProjectStore,
    StorageConfigurationError,
    create_project_store,
)


def test_database_storage_requires_database_url_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GUIDESYNC_DATABASE_URL", raising=False)
    monkeypatch.delenv("GUIDESYNC_STORAGE_MODE", raising=False)

    with pytest.raises(StorageConfigurationError, match="GUIDESYNC_DATABASE_URL"):
        create_project_store()


def test_file_storage_requires_explicit_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GUIDESYNC_DATABASE_URL", raising=False)
    monkeypatch.setenv("GUIDESYNC_STORAGE_MODE", "file")

    assert isinstance(create_project_store(), FileProjectStore)


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
        findings=[
            ValidationFinding(
                severity="warning",
                check="tool.pagination",
                message="Tool result was paginated.",
                evidence_refs=["file-summary:repo:docs/guide.md"],
                artifact_refs=["/tmp/file-summary.json"],
            )
        ],
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
    assert loaded.findings[0].evidence_refs == ["file-summary:repo:docs/guide.md"]
    assert loaded.findings[0].artifact_refs == ["/tmp/file-summary.json"]

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
    assert summaries[0].effective_model_configuration is not None
    assert summaries[0].effective_model_configuration.base_url == "http://localhost:1234/v1"


def test_storage_schema_compatibility_aliases_models() -> None:
    assert storage_schema.metadata is report_runs_table.metadata
    assert storage_schema.report_runs_table is report_runs_table


def test_file_knowledge_store_reads_legacy_file_node_kind(tmp_path: Path) -> None:
    path = tmp_path / "knowledge" / "store.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "index_runs": [],
                "nodes": [
                    {
                        "id": "doc-legacy",
                        "project_id": "project-legacy",
                        "repo": "repo",
                        "kind": "file",
                        "name": "Legacy guide",
                        "qualified_name": "repo:docs/guide.md",
                        "path": "docs/guide.md",
                        "metadata": {"commit_sha": "abc123", "tags": ["legacy"]},
                    },
                    {
                        "id": "symbol-legacy",
                        "project_id": "project-legacy",
                        "repo": "repo",
                        "kind": "symbol",
                        "name": "LegacySymbol",
                        "qualified_name": "repo:src/legacy.py:LegacySymbol",
                        "path": "src/legacy.py",
                        "metadata": {"tags": ["code"]},
                    },
                    {
                        "id": "config-legacy",
                        "project_id": "project-legacy",
                        "repo": "repo",
                        "kind": "config",
                        "name": "pyproject.toml",
                        "qualified_name": "repo:pyproject.toml",
                        "path": "pyproject.toml",
                        "metadata": {"tags": ["config"]},
                    }
                ],
                "edges": [],
                "chunks": [],
                "annotation_runs": [],
                "annotations": [],
                "concepts": [],
                "annotation_edges": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    refs = FileKnowledgeStore(path).document_refs(project_id="project-legacy")

    assert len(refs.documents) == 1
    assert refs.documents[0].id == "doc-legacy"
    assert refs.documents[0].source_commit == "abc123"
    assert refs.documents[0].tags == ["legacy"]


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


def test_database_project_store_updates_project_without_breaking_profiles(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'project-profile-fk.db'}"
    project_store = DatabaseProjectStore(database_url)
    profile_store = DatabaseProjectProfileStore(database_url)

    def enable_foreign_keys(dbapi_connection: SQLiteConnection, _: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    event.listen(project_store.engine, "connect", enable_foreign_keys)
    event.listen(profile_store.engine, "connect", enable_foreign_keys)

    saved = project_store.save(
        ProjectCreate(
            name="Profiled project",
            documentation_instructions="Keep docs grounded in current repository state.",
        )
    )
    profile_store.save(
        ProjectProfileSnapshot(
            id="profile-for-existing-project",
            project_id=saved.id,
            prompt_version="project-profile-analyzer-v1",
            status=ProjectProfileStatus.COMPLETED,
            summary="Profile already exists for this project.",
        )
    )

    updated = project_store.save(
        ProjectCreate.model_validate(
            saved.model_copy(update={"description": "Repository cache refreshed."}).model_dump(
                mode="python"
            )
        ),
        project_id=saved.id,
    )

    latest_profile = profile_store.latest(saved.id)
    assert updated.id == saved.id
    assert updated.description == "Repository cache refreshed."
    assert latest_profile is not None
    assert latest_profile.id == "profile-for-existing-project"


def test_database_project_profile_store_round_trip(tmp_path: Path) -> None:
    store = DatabaseProjectProfileStore(f"sqlite+pysqlite:///{tmp_path / 'profiles.db'}")
    profile = ProjectProfileSnapshot(
        id="profile-round-trip",
        project_id="project-round-trip",
        status=ProjectProfileStatus.COMPLETED,
        version=2,
        prompt_version="project-profile-analyzer-v1",
        summary="GuideSync keeps documentation updates grounded in repository evidence.",
        project_description="GuideSync profiles repositories before generating documentation.",
        project_structure=["src/: backend application", "frontend/: React UI"],
        architecture=["Repository evidence pipeline", "Documentation update workflow"],
        core_concepts=["project profile", "knowledge base", "documentation workflow"],
        workflows=["Create project", "Run analysis", "Review report"],
        key_terms=["guidesync", "documentation", "evidence"],
        agent_context="GuideSync uses profile context to ground downstream agents.",
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
        model_metadata={"provider": "local_http", "model": "openai:test"},
        tool_trace_refs=["project-profile-tool:1:read_file_window:repo-primary"],
        validation_findings=[
            ValidationFinding(
                severity="warning",
                check="project-profile.test",
                message="Review taxonomy confidence.",
            )
        ],
    )

    store.save(profile)
    loaded = store.get("profile-round-trip")
    latest = store.latest("project-round-trip")

    assert loaded is not None
    assert loaded.status == ProjectProfileStatus.COMPLETED
    assert loaded.version == 2
    assert loaded.project_description.startswith("GuideSync profiles")
    assert loaded.project_structure == ["src/: backend application", "frontend/: React UI"]
    assert loaded.core_concepts == [
        "project profile",
        "knowledge base",
        "documentation workflow",
    ]
    assert loaded.agent_context.startswith("GuideSync uses profile context")
    assert loaded.repository_map[0].cache_status == RepositoryCacheStatus.READY
    assert loaded.source_refs[0].docs_path == "docs/"
    assert loaded.model_metadata["provider"] == "local_http"
    assert loaded.tool_trace_refs == ["project-profile-tool:1:read_file_window:repo-primary"]
    assert loaded.validation_findings[0].check == "project-profile.test"
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
        annotation_payloads = [
            json.dumps(dict(row._mapping), default=str)
            for table in (
                knowledge_annotation_runs_table,
                knowledge_annotations_table,
                knowledge_concepts_table,
                knowledge_annotation_edges_table,
            )
            for row in connection.execute(select(table)).all()
        ]

    assert chunk_texts
    assert full_body not in chunk_texts
    assert all(
        "Do not persist this exact long implementation detail" not in text for text in chunk_texts
    )
    assert annotation_payloads
    assert all(full_body not in payload for payload in annotation_payloads)
    assert all(
        "Do not persist this exact long implementation detail" not in payload
        for payload in annotation_payloads
    )


def test_changed_docs_reindex_preserves_unaffected_concepts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "alpha.md").write_text(
        "# Alpha guide\n\nAlphaPage documents model configuration.",
        encoding="utf-8",
    )
    (repo / "docs" / "beta.md").write_text(
        "# Beta guide\n\nBetaPage documents repository management.",
        encoding="utf-8",
    )
    taxonomy = ProjectTaxonomy(
        version="profile-1:v1",
        components=["AlphaPage", "BetaPage"],
        documentation_areas=["alpha guide", "beta guide"],
        domain_terms=["model configuration", "repository management"],
    )
    store = DatabaseKnowledgeStore(f"sqlite+pysqlite:///{tmp_path / 'changed-docs.db'}")

    full_snapshot = build_knowledge_snapshot(
        KnowledgeIndexRequest(
            project_id="project-concepts",
            repositories=[RepositoryInput(name="fixture", path=repo, paths=["docs"])],
            taxonomy=taxonomy,
        )
    )
    store.save_snapshot(full_snapshot)

    (repo / "docs" / "alpha.md").write_text(
        "# Alpha guide\n\nAlphaPage documents updated model configuration.",
        encoding="utf-8",
    )
    changed_snapshot = build_knowledge_snapshot(
        KnowledgeIndexRequest(
            project_id="project-concepts",
            repositories=[RepositoryInput(name="fixture", path=repo, paths=["docs/alpha.md"])],
            taxonomy=taxonomy,
        )
    )
    store.save_changed_docs_snapshot(changed_snapshot, {"docs/alpha.md"})

    with store.engine.begin() as connection:
        concepts = {
            row.canonical_value
            for row in connection.execute(select(knowledge_concepts_table)).all()
        }

    assert {"AlphaPage", "BetaPage"} <= concepts


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
