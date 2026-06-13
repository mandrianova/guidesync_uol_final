from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    insert,
    select,
)

from guidesync_agent.schemas import (
    GuideSyncRunResult,
    ProjectConfig,
    ProjectCreate,
    ProjectDocumentation,
    ProjectRepository,
    RunSummary,
)


class RunStore(Protocol):
    def initialize(self) -> None: ...

    def save(self, result: GuideSyncRunResult) -> None: ...

    def get(self, run_id: str) -> GuideSyncRunResult | None: ...

    def list_runs(self, project_id: str | None = None) -> list[RunSummary]: ...

    def claim_next_queued_run(self) -> GuideSyncRunResult | None: ...


class ProjectStore(Protocol):
    def initialize(self) -> None: ...

    def list_projects(self) -> list[ProjectConfig]: ...

    def save(self, project: ProjectCreate, project_id: str | None = None) -> ProjectConfig: ...

    def get(self, project_id: str) -> ProjectConfig | None: ...


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
        return result


metadata = MetaData()
runs_table = Table(
    "guidesync_runs",
    metadata,
    Column("run_id", String(128), primary_key=True),
    Column("status", String(32), nullable=False),
    Column("provider", String(64), nullable=True),
    Column("model", String(255), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
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


class DatabaseRunStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        metadata.create_all(self.engine)

    def save(self, result: GuideSyncRunResult) -> None:
        self.initialize()
        payload = result.model_dump(mode="json")
        provider = result.provider_metadata.provider if result.provider_metadata else None
        model = result.provider_metadata.model if result.provider_metadata else None
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(runs_table.c.created_at).where(runs_table.c.run_id == result.run_id)
            ).one_or_none()
            connection.execute(delete(runs_table).where(runs_table.c.run_id == result.run_id))
            connection.execute(
                insert(runs_table).values(
                    run_id=result.run_id,
                    status=result.status,
                    provider=provider,
                    model=model,
                    created_at=existing.created_at if existing else now,
                    updated_at=now,
                    payload=payload,
                )
            )

    def get(self, run_id: str) -> GuideSyncRunResult | None:
        self.initialize()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(runs_table.c.payload).where(runs_table.c.run_id == run_id)
            ).one_or_none()
        if row is None:
            return None
        return GuideSyncRunResult.model_validate(row.payload)

    def list_runs(self, project_id: str | None = None) -> list[RunSummary]:
        self.initialize()
        query = select(
            runs_table.c.payload,
            runs_table.c.created_at,
            runs_table.c.updated_at,
        ).order_by(runs_table.c.updated_at.desc())
        if project_id:
            query = query.where(runs_table.c.run_id.like(f"{project_id}-%"))
        with self.engine.begin() as connection:
            rows = connection.execute(query).all()
        return [
            run_summary(
                GuideSyncRunResult.model_validate(row.payload),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    def claim_next_queued_run(self) -> GuideSyncRunResult | None:
        self.initialize()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(runs_table.c.payload)
                .where(runs_table.c.status == "queued")
                .order_by(runs_table.c.created_at)
                .limit(1)
            ).one_or_none()
        if row is None:
            return None
        result = GuideSyncRunResult.model_validate(row.payload)
        result.status = "running"
        self.save(result)
        return result


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


def initialize_storage() -> None:
    create_run_store().initialize()
    create_project_store().initialize()


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
