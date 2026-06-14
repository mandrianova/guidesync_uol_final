from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    insert,
    select,
    update,
)

from guidesync_agent.config import provider_config_from_env
from guidesync_agent.schemas import (
    GuideSyncRunResult,
    ModelSettings,
    ModelSettingsUpdate,
    ProjectConfig,
    ProjectCreate,
    ProjectDocumentation,
    ProjectRepository,
    ProviderConfig,
    ProviderKind,
    RunSummary,
)

GLOBAL_MODEL_PROFILE_ID = "global-default"


class RunStore(Protocol):
    def initialize(self) -> None: ...

    def save(self, result: GuideSyncRunResult) -> None: ...

    def get(self, run_id: str) -> GuideSyncRunResult | None: ...

    def list_runs(self, project_id: str | None = None) -> list[RunSummary]: ...

    def claim_next_queued_run(self) -> GuideSyncRunResult | None: ...

    def record_run_event(
        self,
        run_id: str,
        status: str,
        message: str,
        stage: str | None = None,
    ) -> None: ...


class ProjectStore(Protocol):
    def initialize(self) -> None: ...

    def list_projects(self) -> list[ProjectConfig]: ...

    def save(self, project: ProjectCreate, project_id: str | None = None) -> ProjectConfig: ...

    def get(self, project_id: str) -> ProjectConfig | None: ...


class ModelSettingsStore(Protocol):
    def initialize(self) -> None: ...

    def get(self) -> ModelSettings: ...

    def save(self, settings: ModelSettingsUpdate) -> ModelSettings: ...

    def provider_config(self) -> ProviderConfig: ...


class FileRunStore:
    def __init__(self, root: Path = Path("outputs/runs")) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, result: GuideSyncRunResult) -> None:
        path = self.root / f"{result.run_id}.json"
        payload = json.dumps(result.model_dump(mode="json"), indent=2) + "\n"
        path.write_text(payload, encoding="utf-8")

    def get(self, run_id: str) -> GuideSyncRunResult | None:
        path = self.root / f"{run_id}.json"
        if not path.exists():
            return None
        return GuideSyncRunResult.model_validate_json(path.read_text(encoding="utf-8"))

    def list_runs(self, project_id: str | None = None) -> list[RunSummary]:
        self.initialize()
        summaries = []
        for path in self.root.glob("*.json"):
            result = GuideSyncRunResult.model_validate_json(path.read_text(encoding="utf-8"))
            if project_id and not result.run_id.startswith(f"{project_id}-"):
                continue
            timestamp = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            summaries.append(run_summary(result, created_at=timestamp, updated_at=timestamp))
        return sorted(summaries, key=lambda summary: summary.updated_at, reverse=True)

    def claim_next_queued_run(self) -> GuideSyncRunResult | None:
        self.initialize()
        queued = [
            self.get(summary.run_id) for summary in self.list_runs() if summary.status == "queued"
        ]
        result = next((item for item in queued if item is not None), None)
        if result is None:
            return None
        result.status = "running"
        self.save(result)
        self.record_run_event(result.run_id, "running", "Run claimed by local file worker.")
        return result

    def record_run_event(
        self,
        run_id: str,
        status: str,
        message: str,
        stage: str | None = None,
    ) -> None:
        return None


metadata = MetaData()
model_profiles_table = Table(
    "guidesync_model_profiles",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("name", String(255), nullable=False),
    Column("provider", String(64), nullable=False),
    Column("model", String(255), nullable=False),
    Column("base_url", Text, nullable=True),
    Column("api_key_secret_ref", Text, nullable=True),
    Column("is_default", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
report_runs_table = Table(
    "guidesync_report_runs",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("status", String(32), nullable=False),
    Column("mode", String(64), nullable=True),
    Column("goal", Text, nullable=False),
    Column("audience", Text, nullable=False),
    Column(
        "model_profile_id", String(128), ForeignKey("guidesync_model_profiles.id"), nullable=True
    ),
    Column("provider", String(64), nullable=True),
    Column("model", String(255), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("error_message", Text, nullable=True),
    Column("request_snapshot", JSON, nullable=False),
    Column("result_snapshot", JSON, nullable=False),
    Column("filters", JSON, nullable=False),
)
run_events_table = Table(
    "guidesync_report_run_events",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("guidesync_report_runs.id"), nullable=False),
    Column("status", String(32), nullable=False),
    Column("stage", String(128), nullable=True),
    Column("message", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
run_artifacts_table = Table(
    "guidesync_report_artifacts",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("guidesync_report_runs.id"), nullable=False),
    Column("artifact_type", String(64), nullable=False),
    Column("uri", Text, nullable=False),
    Column("content_type", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
evidence_items_table = Table(
    "guidesync_evidence_items",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("guidesync_report_runs.id"), nullable=False),
    Column("source_type", String(64), nullable=False),
    Column("source_ref", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("score", JSON, nullable=True),
    Column("metadata", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
change_classifications_table = Table(
    "guidesync_change_classifications",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("guidesync_report_runs.id"), nullable=False),
    Column("source_ref", Text, nullable=False),
    Column("category", String(128), nullable=False),
    Column("confidence", JSON, nullable=True),
    Column("method", String(128), nullable=False),
    Column("explanation", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
screenshots_table = Table(
    "guidesync_screenshots",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("guidesync_report_runs.id"), nullable=False),
    Column("repository_id", String(128), nullable=True),
    Column("url_or_route", Text, nullable=False),
    Column("artifact_uri", Text, nullable=False),
    Column("viewport", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
projects_table = Table(
    "guidesync_projects",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("description", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
project_repositories_table = Table(
    "guidesync_project_repositories",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=False),
    Column("name", String(255), nullable=False),
    Column("url", Text, nullable=False),
    Column("default_branch", String(255), nullable=True),
    Column("paths", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
project_documentation_table = Table(
    "guidesync_project_documentation",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=False),
    Column("name", String(255), nullable=False),
    Column("description", Text, nullable=True),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

Index("ix_guidesync_project_repositories_project", project_repositories_table.c.project_id)
Index("ix_guidesync_project_documentation_project", project_documentation_table.c.project_id)
Index("ix_guidesync_model_profiles_project", model_profiles_table.c.project_id)
Index(
    "ix_guidesync_report_runs_status_created",
    report_runs_table.c.status,
    report_runs_table.c.created_at,
)
Index(
    "ix_guidesync_report_runs_project_updated",
    report_runs_table.c.project_id,
    report_runs_table.c.updated_at,
)
Index(
    "ix_guidesync_report_run_events_run_created",
    run_events_table.c.run_id,
    run_events_table.c.created_at,
)
Index("ix_guidesync_report_artifacts_run", run_artifacts_table.c.run_id)
Index("ix_guidesync_evidence_items_run", evidence_items_table.c.run_id)
Index("ix_guidesync_change_classifications_run", change_classifications_table.c.run_id)
Index("ix_guidesync_screenshots_run", screenshots_table.c.run_id)


class DatabaseRunStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        metadata.create_all(self.engine)

    def save(self, result: GuideSyncRunResult) -> None:
        self.initialize()
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(report_runs_table.c.created_at).where(
                    report_runs_table.c.id == result.run_id
                )
            ).one_or_none()
            upsert_report_run(connection, result, now, existing.created_at if existing else now)
            replace_run_artifacts(connection, result, now)

    def get(self, run_id: str) -> GuideSyncRunResult | None:
        self.initialize()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(report_runs_table.c.result_snapshot).where(report_runs_table.c.id == run_id)
            ).one_or_none()
        if row is None:
            return None
        return GuideSyncRunResult.model_validate(row.result_snapshot)

    def list_runs(self, project_id: str | None = None) -> list[RunSummary]:
        self.initialize()
        query = select(
            report_runs_table.c.result_snapshot,
            report_runs_table.c.created_at,
            report_runs_table.c.updated_at,
        ).order_by(report_runs_table.c.updated_at.desc())
        if project_id:
            query = query.where(report_runs_table.c.project_id == project_id)
        with self.engine.begin() as connection:
            rows = connection.execute(query).all()
        return [
            run_summary(
                GuideSyncRunResult.model_validate(row.result_snapshot),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    def claim_next_queued_run(self) -> GuideSyncRunResult | None:
        self.initialize()
        now = datetime.now(UTC)
        result: GuideSyncRunResult | None = None
        with self.engine.begin() as connection:
            row = connection.execute(
                select(report_runs_table.c.id, report_runs_table.c.result_snapshot)
                .where(report_runs_table.c.status == "queued")
                .order_by(report_runs_table.c.created_at)
                .limit(1)
            ).one_or_none()
            if row is None:
                return None
            result = GuideSyncRunResult.model_validate(row.result_snapshot)
            result.status = "running"
            claimed = connection.execute(
                update(report_runs_table)
                .where(
                    report_runs_table.c.id == row.id,
                    report_runs_table.c.status == "queued",
                )
                .values(
                    status="running",
                    started_at=now,
                    updated_at=now,
                    result_snapshot=result.model_dump(mode="json"),
                )
            )
            if claimed.rowcount != 1:
                return None
        self.record_run_event(result.run_id, "running", "Run claimed by worker.", "worker")
        return result

    def record_run_event(
        self,
        run_id: str,
        status: str,
        message: str,
        stage: str | None = None,
    ) -> None:
        self.initialize()
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            connection.execute(
                insert(run_events_table).values(
                    id=f"event-{uuid4().hex[:12]}",
                    run_id=run_id,
                    status=status,
                    stage=stage,
                    message=message,
                    created_at=now,
                )
            )


class FileProjectStore:
    def __init__(self, path: Path = Path("outputs/projects.json")) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]\n", encoding="utf-8")

    def list_projects(self) -> list[ProjectConfig]:
        self.initialize()
        return [
            ProjectConfig.model_validate(item)
            for item in json.loads(self.path.read_text(encoding="utf-8"))
        ]

    def save(self, project: ProjectCreate, project_id: str | None = None) -> ProjectConfig:
        projects = self.list_projects()
        now = datetime.now(UTC)
        existing = next((item for item in projects if item.id == project_id), None)
        saved = ProjectConfig(
            id=project_id or f"project-{uuid4().hex[:10]}",
            name=project.name,
            description=project.description,
            repositories=project.repositories,
            documentation=project.documentation,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        projects = [item for item in projects if item.id != saved.id]
        projects.append(saved)
        self.path.write_text(
            json.dumps([item.model_dump(mode="json") for item in projects], indent=2) + "\n",
            encoding="utf-8",
        )
        return saved

    def get(self, project_id: str) -> ProjectConfig | None:
        return next((project for project in self.list_projects() if project.id == project_id), None)


class FileModelSettingsStore:
    def __init__(self, path: Path = Path("outputs/model-settings.json")) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get(self) -> ModelSettings:
        self.initialize()
        if not self.path.exists():
            return model_settings_from_provider_config(provider_config_from_env())
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return ModelSettings.model_validate(
            {
                **payload,
                "api_key": decode_local_api_key(payload.get("api_key_secret_ref")),
                "has_api_key": bool(payload.get("api_key_secret_ref")),
            }
        )

    def save(self, settings: ModelSettingsUpdate) -> ModelSettings:
        existing = self.get()
        api_key = None if settings.clear_api_key else settings.api_key or existing.api_key
        saved = ModelSettings(
            provider=settings.provider,
            model=settings.model,
            base_url=settings.base_url,
            api_key=api_key,
            has_api_key=bool(api_key),
            timeout_seconds=settings.timeout_seconds,
        )
        payload = saved.model_dump(mode="json")
        payload["api_key_secret_ref"] = encode_local_api_key(saved.api_key)
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return saved

    def provider_config(self) -> ProviderConfig:
        settings = self.get()
        return model_settings_to_provider_config(settings)


class DatabaseProjectStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        metadata.create_all(self.engine)

    def list_projects(self) -> list[ProjectConfig]:
        self.initialize()
        with self.engine.begin() as connection:
            rows = connection.execute(select(projects_table).order_by(projects_table.c.name)).all()
        return [project for row in rows if (project := self.get(row.id)) is not None]

    def save(self, project: ProjectCreate, project_id: str | None = None) -> ProjectConfig:
        self.initialize()
        now = datetime.now(UTC)
        existing = self.get(project_id) if project_id else None
        saved = ProjectConfig(
            id=project_id or f"project-{uuid4().hex[:10]}",
            name=project.name,
            description=project.description,
            repositories=project.repositories,
            documentation=project.documentation,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        with self.engine.begin() as connection:
            connection.execute(
                delete(project_repositories_table).where(
                    project_repositories_table.c.project_id == saved.id
                )
            )
            connection.execute(
                delete(project_documentation_table).where(
                    project_documentation_table.c.project_id == saved.id
                )
            )
            connection.execute(delete(projects_table).where(projects_table.c.id == saved.id))
            connection.execute(
                insert(projects_table).values(
                    id=saved.id,
                    name=saved.name,
                    description=saved.description,
                    created_at=saved.created_at,
                    updated_at=saved.updated_at,
                )
            )
            for repository in saved.repositories:
                connection.execute(
                    insert(project_repositories_table).values(
                        id=repository.id,
                        project_id=saved.id,
                        name=repository.name,
                        url=repository.url,
                        default_branch=repository.default_branch,
                        paths=repository.paths,
                        created_at=now,
                        updated_at=now,
                    )
                )
            for document in saved.documentation:
                connection.execute(
                    insert(project_documentation_table).values(
                        id=document.id,
                        project_id=saved.id,
                        name=document.name,
                        description=document.description,
                        content=document.content,
                        created_at=now,
                        updated_at=now,
                    )
                )
        return saved

    def get(self, project_id: str) -> ProjectConfig | None:
        self.initialize()
        with self.engine.begin() as connection:
            project_row = connection.execute(
                select(projects_table).where(projects_table.c.id == project_id)
            ).one_or_none()
            if project_row is None:
                return None
            repo_rows = connection.execute(
                select(project_repositories_table).where(
                    project_repositories_table.c.project_id == project_id
                )
            ).all()
            doc_rows = connection.execute(
                select(project_documentation_table).where(
                    project_documentation_table.c.project_id == project_id
                )
            ).all()
        return ProjectConfig(
            id=project_row.id,
            name=project_row.name,
            description=project_row.description,
            repositories=[
                ProjectRepository(
                    id=row.id,
                    name=row.name,
                    url=row.url,
                    default_branch=row.default_branch,
                    paths=row.paths,
                )
                for row in repo_rows
            ],
            documentation=[
                ProjectDocumentation(
                    id=row.id,
                    name=row.name,
                    description=row.description,
                    content=row.content,
                )
                for row in doc_rows
            ],
            created_at=project_row.created_at,
            updated_at=project_row.updated_at,
        )


class DatabaseModelSettingsStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        metadata.create_all(self.engine)

    def get(self) -> ModelSettings:
        self.initialize()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(model_profiles_table).where(
                    model_profiles_table.c.id == GLOBAL_MODEL_PROFILE_ID
                )
            ).one_or_none()
        if row is None:
            return model_settings_from_provider_config(provider_config_from_env())
        api_key = decode_local_api_key(row.api_key_secret_ref)
        return ModelSettings(
            provider=ProviderKind(row.provider),
            model=row.model,
            base_url=row.base_url,
            api_key=api_key,
            has_api_key=bool(api_key),
            timeout_seconds=60,
        )

    def save(self, settings: ModelSettingsUpdate) -> ModelSettings:
        self.initialize()
        existing = self.get()
        api_key = None if settings.clear_api_key else settings.api_key or existing.api_key
        saved = ModelSettings(
            provider=settings.provider,
            model=settings.model,
            base_url=settings.base_url,
            api_key=api_key,
            has_api_key=bool(api_key),
            timeout_seconds=settings.timeout_seconds,
        )
        now = datetime.now(UTC)
        values = {
            "id": GLOBAL_MODEL_PROFILE_ID,
            "project_id": None,
            "name": "Global default",
            "provider": saved.provider.value,
            "model": saved.model,
            "base_url": saved.base_url,
            "api_key_secret_ref": encode_local_api_key(saved.api_key),
            "is_default": True,
            "updated_at": now,
        }
        with self.engine.begin() as connection:
            existing_row = connection.execute(
                select(model_profiles_table.c.id).where(
                    model_profiles_table.c.id == GLOBAL_MODEL_PROFILE_ID
                )
            ).one_or_none()
            if existing_row is None:
                connection.execute(insert(model_profiles_table).values(created_at=now, **values))
            else:
                connection.execute(
                    update(model_profiles_table)
                    .where(model_profiles_table.c.id == GLOBAL_MODEL_PROFILE_ID)
                    .values(**values)
                )
        return saved

    def provider_config(self) -> ProviderConfig:
        settings = self.get()
        return model_settings_to_provider_config(settings)


def create_run_store() -> RunStore:
    database_url = os.environ.get("GUIDESYNC_DATABASE_URL")
    if database_url:
        return DatabaseRunStore(database_url)
    return FileRunStore()


def create_project_store() -> ProjectStore:
    database_url = os.environ.get("GUIDESYNC_DATABASE_URL")
    if database_url:
        return DatabaseProjectStore(database_url)
    return FileProjectStore()


def create_model_settings_store() -> ModelSettingsStore:
    database_url = os.environ.get("GUIDESYNC_DATABASE_URL")
    if database_url:
        return DatabaseModelSettingsStore(database_url)
    return FileModelSettingsStore()


def initialize_storage() -> None:
    create_run_store().initialize()
    create_project_store().initialize()
    create_model_settings_store().initialize()


def model_settings_to_provider_config(settings: ModelSettings) -> ProviderConfig:
    return ProviderConfig(
        provider=settings.provider,
        model=settings.model,
        base_url=settings.base_url,
        api_key=settings.api_key,
        timeout_seconds=settings.timeout_seconds,
        metadata={"model_profile_id": GLOBAL_MODEL_PROFILE_ID},
    )


def model_settings_from_provider_config(config: ProviderConfig) -> ModelSettings:
    return ModelSettings(
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        has_api_key=bool(config.api_key),
        timeout_seconds=config.timeout_seconds,
    )


def encode_local_api_key(api_key: str | None) -> str | None:
    return f"local-inline:{api_key}" if api_key else None


def decode_local_api_key(secret_ref: str | None) -> str | None:
    if not secret_ref:
        return None
    if secret_ref.startswith("local-inline:"):
        return secret_ref.removeprefix("local-inline:")
    return None


def run_summary(
    result: GuideSyncRunResult,
    *,
    created_at: datetime,
    updated_at: datetime,
) -> RunSummary:
    provider = result.provider_metadata.provider if result.provider_metadata else None
    model = result.provider_metadata.model if result.provider_metadata else None
    return RunSummary(
        run_id=result.run_id,
        status=result.status,
        title=result.request.report.title,
        created_at=created_at,
        updated_at=updated_at,
        provider=provider,
        model=model,
        artifacts=result.artifacts,
    )


def upsert_report_run(
    connection, result: GuideSyncRunResult, now: datetime, created_at: datetime
) -> None:
    provider = (
        result.provider_metadata.provider
        if result.provider_metadata
        else result.request.provider.provider
    )
    model = (
        result.provider_metadata.model
        if result.provider_metadata
        else result.request.provider.model
    )
    started_at = result.provider_metadata.started_at if result.provider_metadata else None
    completed_at = result.provider_metadata.completed_at if result.provider_metadata else None
    error_message = next(
        (finding.message for finding in result.findings if finding.severity == "error"),
        None,
    )
    filters = {
        "repositories": [
            {
                "name": repository.name,
                "url": repository.url,
                "ref": repository.ref,
                "since": repository.since,
                "until": repository.until,
                "branches": repository.branches,
                "paths": repository.paths,
            }
            for repository in result.request.repositories
        ]
    }
    existing = connection.execute(
        select(report_runs_table.c.id).where(report_runs_table.c.id == result.run_id)
    ).one_or_none()
    values = {
        "id": result.run_id,
        "project_id": project_id_from_run_id(result.run_id),
        "status": result.status,
        "mode": None,
        "goal": result.request.goal,
        "audience": result.request.audience,
        "model_profile_id": None,
        "provider": provider.value if hasattr(provider, "value") else provider,
        "model": model,
        "started_at": started_at,
        "completed_at": completed_at,
        "updated_at": now,
        "error_message": error_message,
        "request_snapshot": result.request.model_dump(mode="json"),
        "result_snapshot": result.model_dump(mode="json"),
        "filters": filters,
    }
    if existing is None:
        connection.execute(insert(report_runs_table).values(created_at=created_at, **values))
        return
    connection.execute(
        update(report_runs_table).where(report_runs_table.c.id == result.run_id).values(**values)
    )


def replace_run_artifacts(connection, result: GuideSyncRunResult, now: datetime) -> None:
    connection.execute(
        delete(run_artifacts_table).where(run_artifacts_table.c.run_id == result.run_id)
    )
    for filename, uri in result.artifacts.items():
        connection.execute(
            insert(run_artifacts_table).values(
                id=f"artifact-{uuid4().hex[:12]}",
                run_id=result.run_id,
                artifact_type=filename,
                uri=uri,
                content_type=content_type_for_artifact(filename),
                created_at=now,
            )
        )


def project_id_from_run_id(run_id: str) -> str | None:
    if not run_id.startswith("project-"):
        return None
    parts = run_id.split("-")
    if len(parts) < 3:
        return None
    return "-".join(parts[:2])


def content_type_for_artifact(filename: str) -> str | None:
    if filename.endswith(".html"):
        return "text/html; charset=utf-8"
    if filename.endswith(".md"):
        return "text/markdown; charset=utf-8"
    if filename.endswith(".json"):
        return "application/json; charset=utf-8"
    return None
