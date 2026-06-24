from __future__ import annotations

from pathlib import Path

from guidesync_agent.schemas import (
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ModelSettingsUpdate,
    ProjectCreate,
    ProjectDocumentation,
    ProjectRepository,
    ProviderKind,
)
from guidesync_agent.storage import (
    DatabaseModelSettingsStore,
    DatabaseProjectStore,
    DatabaseRunStore,
)


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
    assert summaries[0].title == "GuideSync release notes"


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
