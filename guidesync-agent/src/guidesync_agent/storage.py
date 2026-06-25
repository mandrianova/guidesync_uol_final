from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.engine import Connection, Row

from guidesync_agent.config import provider_config_from_env
from guidesync_agent.knowledge_tagging import tokenize_text
from guidesync_agent.schemas import (
    Audience,
    EffectiveModelConfiguration,
    GuideSyncRunResult,
    KnowledgeChunk,
    KnowledgeDocumentRef,
    KnowledgeDocumentRefs,
    KnowledgeEdge,
    KnowledgeGraphSnapshot,
    KnowledgeIndexRequest,
    KnowledgeIndexRun,
    KnowledgeIndexStatus,
    KnowledgeIndexSummary,
    KnowledgeNode,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    KnowledgeSectionRef,
    KnowledgeTag,
    ModelSettings,
    ModelSettingsUpdate,
    ProjectConfig,
    ProjectCreate,
    ProjectDocumentation,
    ProjectProfileRepositoryMapItem,
    ProjectProfileSnapshot,
    ProjectProfileSourceRef,
    ProjectProfileStatus,
    ProjectRepository,
    ProviderConfig,
    ProviderKind,
    RepositoryCacheStatus,
    RunSummary,
    ThinkingSetting,
)
from guidesync_agent.storage_schema import (
    knowledge_chunks_table,
    knowledge_edges_table,
    knowledge_index_runs_table,
    knowledge_nodes_table,
    metadata,
    model_profiles_table,
    project_documentation_table,
    project_profiles_table,
    project_repositories_table,
    projects_table,
    report_runs_table,
    run_artifacts_table,
    run_events_table,
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


class ProjectProfileStore(Protocol):
    def initialize(self) -> None: ...

    def save(self, profile: ProjectProfileSnapshot) -> ProjectProfileSnapshot: ...

    def get(self, profile_id: str) -> ProjectProfileSnapshot | None: ...

    def latest(self, project_id: str) -> ProjectProfileSnapshot | None: ...

    def list_profiles(self, project_id: str) -> list[ProjectProfileSnapshot]: ...


class ModelSettingsStore(Protocol):
    def initialize(self) -> None: ...

    def get(self) -> ModelSettings: ...

    def list_profiles(self) -> list[ModelSettings]: ...

    def save(self, settings: ModelSettingsUpdate) -> ModelSettings: ...

    def save_profile(
        self,
        settings: ModelSettingsUpdate,
        profile_id: str | None = None,
        make_default: bool = False,
    ) -> ModelSettings: ...

    def set_default(self, profile_id: str) -> ModelSettings | None: ...

    def delete_profile(self, profile_id: str) -> ModelSettings | None: ...

    def provider_config(self) -> ProviderConfig: ...


class KnowledgeStore(Protocol):
    def initialize(self) -> None: ...

    def save_snapshot(self, snapshot: KnowledgeGraphSnapshot) -> None: ...

    def get_index_run(self, run_id: str) -> KnowledgeIndexRun | None: ...

    def list_index_runs(self, project_id: str | None = None) -> list[KnowledgeIndexRun]: ...

    def search(self, request: KnowledgeSearchRequest) -> list[KnowledgeSearchResult]: ...

    def document_refs(self, project_id: str | None = None) -> KnowledgeDocumentRefs: ...

    def tag_cloud(self, project_id: str | None = None) -> list[KnowledgeTag]: ...

    def related_edges(
        self,
        node_ids: set[str],
        project_id: str | None = None,
    ) -> list[KnowledgeEdge]: ...


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
        return run_result_from_snapshot(path.read_text(encoding="utf-8"))

    def list_runs(self, project_id: str | None = None) -> list[RunSummary]:
        self.initialize()
        summaries = []
        for path in self.root.glob("*.json"):
            result = run_result_from_snapshot(path.read_text(encoding="utf-8"))
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
        return run_result_from_snapshot(row.result_snapshot)

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
                run_result_from_snapshot(row.result_snapshot),
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
            result = run_result_from_snapshot(row.result_snapshot)
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
            audience=project.audience,
            documentation_instructions=project.documentation_instructions,
            knowledge_base_repository_id=project.knowledge_base_repository_id,
            knowledge_base_ref=project.knowledge_base_ref,
            knowledge_base_path=project.knowledge_base_path,
            analysis_paths=project.analysis_paths,
            credential_ref=project.credential_ref,
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


class FileProjectProfileStore:
    def __init__(self, path: Path = Path("outputs/project-profiles/store.json")) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write([])

    def save(self, profile: ProjectProfileSnapshot) -> ProjectProfileSnapshot:
        self.initialize()
        profiles = [item for item in self._read() if item["id"] != profile.id]
        profiles.append(profile.model_dump(mode="json"))
        self._write(profiles)
        return profile

    def get(self, profile_id: str) -> ProjectProfileSnapshot | None:
        self.initialize()
        return next(
            (
                ProjectProfileSnapshot.model_validate(item)
                for item in self._read()
                if item["id"] == profile_id
            ),
            None,
        )

    def latest(self, project_id: str) -> ProjectProfileSnapshot | None:
        return next(iter(self.list_profiles(project_id)), None)

    def list_profiles(self, project_id: str) -> list[ProjectProfileSnapshot]:
        self.initialize()
        profiles = [
            ProjectProfileSnapshot.model_validate(item)
            for item in self._read()
            if item["project_id"] == project_id
        ]
        return sorted(
            profiles,
            key=lambda profile: (profile.version, profile.created_at),
            reverse=True,
        )

    def _read(self) -> list[dict[str, object]]:
        return cast(list[dict[str, object]], json.loads(self.path.read_text(encoding="utf-8")))

    def _write(self, profiles: list[dict[str, object]]) -> None:
        self.path.write_text(json.dumps(profiles, indent=2) + "\n", encoding="utf-8")


class FileModelSettingsStore:
    def __init__(self, path: Path = Path("outputs/model-settings.json")) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get(self) -> ModelSettings:
        profiles = self.list_profiles()
        return next((profile for profile in profiles if profile.is_default), profiles[0])

    def list_profiles(self) -> list[ModelSettings]:
        self.initialize()
        if not self.path.exists():
            return [model_settings_from_provider_config(provider_config_from_env())]
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if "profiles" not in payload:
            return [
                ModelSettings.model_validate(
                    {
                        **payload,
                        "id": payload.get("id") or GLOBAL_MODEL_PROFILE_ID,
                        "name": payload.get("name") or "Default model",
                        "api_key": decode_local_api_key(payload.get("api_key_secret_ref")),
                        "has_api_key": bool(payload.get("api_key_secret_ref")),
                        "is_default": True,
                    }
                )
            ]
        default_profile_id = payload.get("default_profile_id") or GLOBAL_MODEL_PROFILE_ID
        profiles = [
            ModelSettings.model_validate(
                {
                    **profile,
                    "api_key": decode_local_api_key(profile.get("api_key_secret_ref")),
                    "has_api_key": bool(profile.get("api_key_secret_ref")),
                    "is_default": profile.get("id") == default_profile_id,
                }
            )
            for profile in payload.get("profiles", [])
        ]
        if profiles:
            return profiles
        return [model_settings_from_provider_config(provider_config_from_env())]

    def save(self, settings: ModelSettingsUpdate) -> ModelSettings:
        return self.save_profile(settings, profile_id=self.get().id, make_default=True)

    def save_profile(
        self,
        settings: ModelSettingsUpdate,
        profile_id: str | None = None,
        make_default: bool = False,
    ) -> ModelSettings:
        profiles = self.list_profiles()
        default_id = next(
            (profile.id for profile in profiles if profile.is_default),
            profiles[0].id,
        )
        target_id = profile_id or f"model-{uuid4().hex[:10]}"
        existing = next((profile for profile in profiles if profile.id == target_id), None)
        existing_api_key = existing.api_key if existing else None
        api_key = None if settings.clear_api_key else settings.api_key or existing_api_key
        saved = ModelSettings(
            id=target_id,
            name=settings.name or (existing.name if existing else "Custom model"),
            provider=settings.provider,
            model=settings.model,
            base_url=settings.base_url,
            api_key=api_key,
            has_api_key=bool(api_key),
            is_default=make_default or target_id == default_id,
            timeout_seconds=settings.timeout_seconds,
            thinking=settings.thinking,
        )
        next_profiles = [profile for profile in profiles if profile.id != target_id]
        next_profiles.append(saved)
        self._write_profiles(next_profiles, saved.id if saved.is_default else default_id)
        return saved

    def set_default(self, profile_id: str) -> ModelSettings | None:
        profiles = self.list_profiles()
        selected = next((profile for profile in profiles if profile.id == profile_id), None)
        if selected is None:
            return None
        self._write_profiles(profiles, profile_id)
        return ModelSettings.model_validate({**selected.model_dump(), "is_default": True})

    def delete_profile(self, profile_id: str) -> ModelSettings | None:
        if profile_id == GLOBAL_MODEL_PROFILE_ID:
            return None
        profiles = self.list_profiles()
        selected = next((profile for profile in profiles if profile.id == profile_id), None)
        if selected is None or selected.is_default or len(profiles) <= 1:
            return None
        self._write_profiles(
            [profile for profile in profiles if profile.id != profile_id],
            self.get().id,
        )
        return self.get()

    def _write_profiles(self, profiles: list[ModelSettings], default_profile_id: str) -> None:
        serialized_profiles = []
        for profile in profiles:
            payload = profile.model_dump(mode="json")
            payload["api_key_secret_ref"] = encode_local_api_key(profile.api_key)
            payload.pop("has_api_key", None)
            payload.pop("api_key", None)
            payload["is_default"] = profile.id == default_profile_id
            serialized_profiles.append(payload)
        payload = {
            "default_profile_id": default_profile_id,
            "profiles": serialized_profiles,
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def provider_config(self) -> ProviderConfig:
        settings = self.get()
        return model_settings_to_provider_config(settings)


class FileKnowledgeStore:
    def __init__(self, path: Path = Path("outputs/knowledge/store.json")) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(self._blank_state())

    def save_snapshot(self, snapshot: KnowledgeGraphSnapshot) -> None:
        self.initialize()
        data = self._read()
        project_id = snapshot.run.project_id
        data["index_runs"] = [
            item for item in data["index_runs"] if item["id"] != snapshot.run.id
        ]
        data["index_runs"].append(snapshot.run.model_dump(mode="json"))
        data["nodes"] = [
            item for item in data["nodes"] if item.get("project_id") != project_id
        ]
        data["edges"] = [
            item for item in data["edges"] if item.get("project_id") != project_id
        ]
        data["chunks"] = [
            item for item in data["chunks"] if item.get("project_id") != project_id
        ]
        data["nodes"].extend(node.model_dump(mode="json") for node in snapshot.nodes)
        data["edges"].extend(edge.model_dump(mode="json") for edge in snapshot.edges)
        data["chunks"].extend(chunk.model_dump(mode="json") for chunk in snapshot.chunks)
        self._write(data)

    def get_index_run(self, run_id: str) -> KnowledgeIndexRun | None:
        self.initialize()
        return next(
            (
                KnowledgeIndexRun.model_validate(item)
                for item in self._read()["index_runs"]
                if item["id"] == run_id
            ),
            None,
        )

    def list_index_runs(self, project_id: str | None = None) -> list[KnowledgeIndexRun]:
        self.initialize()
        runs = [
            KnowledgeIndexRun.model_validate(item)
            for item in self._read()["index_runs"]
            if project_id is None or item.get("project_id") == project_id
        ]
        return sorted(
            runs,
            key=lambda run: run.completed_at or run.started_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

    def search(self, request: KnowledgeSearchRequest) -> list[KnowledgeSearchResult]:
        self.initialize()
        data = self._read()
        nodes = [KnowledgeNode.model_validate(item) for item in data["nodes"]]
        chunks = [KnowledgeChunk.model_validate(item) for item in data["chunks"]]
        return score_knowledge_search(request, nodes, chunks)

    def document_refs(self, project_id: str | None = None) -> KnowledgeDocumentRefs:
        self.initialize()
        data = self._read()
        nodes = [KnowledgeNode.model_validate(item) for item in data["nodes"]]
        chunks = [KnowledgeChunk.model_validate(item) for item in data["chunks"]]
        return knowledge_document_refs(nodes, chunks, project_id=project_id)

    def tag_cloud(self, project_id: str | None = None) -> list[KnowledgeTag]:
        self.initialize()
        nodes = [KnowledgeNode.model_validate(item) for item in self._read()["nodes"]]
        return knowledge_tag_cloud(nodes, project_id=project_id)

    def related_edges(
        self,
        node_ids: set[str],
        project_id: str | None = None,
    ) -> list[KnowledgeEdge]:
        self.initialize()
        return [
            edge
            for item in self._read()["edges"]
            if (edge := KnowledgeEdge.model_validate(item))
            and (project_id is None or edge.project_id == project_id)
            and (edge.source_node_id in node_ids or edge.target_node_id in node_ids)
        ]

    def _read(self) -> dict[str, list[dict[str, object]]]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, list[dict[str, object]]]) -> None:
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def _blank_state(self) -> dict[str, list[dict[str, object]]]:
        return {"index_runs": [], "nodes": [], "edges": [], "chunks": []}


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
            audience=project.audience,
            documentation_instructions=project.documentation_instructions,
            knowledge_base_repository_id=project.knowledge_base_repository_id,
            knowledge_base_ref=project.knowledge_base_ref,
            knowledge_base_path=project.knowledge_base_path,
            analysis_paths=project.analysis_paths,
            credential_ref=project.credential_ref,
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
                    audience=saved.audience.value,
                    documentation_instructions=saved.documentation_instructions,
                    knowledge_base_repository_id=saved.knowledge_base_repository_id,
                    knowledge_base_ref=saved.knowledge_base_ref,
                    knowledge_base_path=saved.knowledge_base_path,
                    analysis_paths=saved.analysis_paths,
                    credential_ref=saved.credential_ref,
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
                        analysis_paths=repository.analysis_paths,
                        credential_ref=repository.credential_ref,
                        cache_status=repository.cache_status.value,
                        local_path=repository.local_path,
                        current_commit=repository.current_commit,
                        cache_warnings=repository.cache_warnings,
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
                        path=document.path,
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
            audience=Audience(project_row.audience),
            documentation_instructions=project_row.documentation_instructions,
            knowledge_base_repository_id=project_row.knowledge_base_repository_id,
            knowledge_base_ref=project_row.knowledge_base_ref,
            knowledge_base_path=project_row.knowledge_base_path,
            analysis_paths=project_row.analysis_paths,
            credential_ref=project_row.credential_ref,
            repositories=[
                ProjectRepository(
                    id=row.id,
                    name=row.name,
                    url=row.url,
                    default_branch=row.default_branch,
                    analysis_paths=row.analysis_paths,
                    credential_ref=row.credential_ref,
                    cache_status=RepositoryCacheStatus(row.cache_status),
                    local_path=row.local_path,
                    current_commit=row.current_commit,
                    cache_warnings=row.cache_warnings,
                )
                for row in repo_rows
            ],
            documentation=[
                ProjectDocumentation(
                    id=row.id,
                    name=row.name,
                    description=row.description,
                    path=row.path,
                )
                for row in doc_rows
            ],
            created_at=project_row.created_at,
            updated_at=project_row.updated_at,
        )


class DatabaseProjectProfileStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        metadata.create_all(self.engine)

    def save(self, profile: ProjectProfileSnapshot) -> ProjectProfileSnapshot:
        self.initialize()
        values = {
            "id": profile.id,
            "project_id": profile.project_id,
            "status": profile.status.value,
            "version": profile.version,
            "prompt_version": profile.prompt_version,
            "summary": profile.summary,
            "architecture": profile.architecture,
            "workflows": profile.workflows,
            "key_terms": profile.key_terms,
            "repository_map": [
                item.model_dump(mode="json") for item in profile.repository_map
            ],
            "source_refs": [item.model_dump(mode="json") for item in profile.source_refs],
            "warnings": profile.warnings,
            "uncertainty_notes": profile.uncertainty_notes,
            "artifact_uris": profile.artifact_uris,
            "created_at": profile.created_at,
            "completed_at": profile.completed_at,
            "error_message": profile.error_message,
        }
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(project_profiles_table.c.id).where(project_profiles_table.c.id == profile.id)
            ).one_or_none()
            if existing is None:
                connection.execute(insert(project_profiles_table).values(**values))
            else:
                connection.execute(
                    update(project_profiles_table)
                    .where(project_profiles_table.c.id == profile.id)
                    .values(**values)
                )
        return profile

    def get(self, profile_id: str) -> ProjectProfileSnapshot | None:
        self.initialize()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(project_profiles_table).where(project_profiles_table.c.id == profile_id)
            ).one_or_none()
        return project_profile_from_row(row) if row else None

    def latest(self, project_id: str) -> ProjectProfileSnapshot | None:
        return next(iter(self.list_profiles(project_id)), None)

    def list_profiles(self, project_id: str) -> list[ProjectProfileSnapshot]:
        self.initialize()
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(project_profiles_table)
                .where(project_profiles_table.c.project_id == project_id)
                .order_by(
                    project_profiles_table.c.version.desc(),
                    project_profiles_table.c.created_at.desc(),
                )
            ).all()
        return [project_profile_from_row(row) for row in rows]


class DatabaseModelSettingsStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        metadata.create_all(self.engine)

    def get(self) -> ModelSettings:
        profiles = self.list_profiles()
        return next((profile for profile in profiles if profile.is_default), profiles[0])

    def list_profiles(self) -> list[ModelSettings]:
        self.initialize()
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(model_profiles_table)
                .where(model_profiles_table.c.project_id.is_(None))
                .order_by(model_profiles_table.c.is_default.desc(), model_profiles_table.c.name)
            ).all()
        profiles = []
        for row in rows:
            api_key = decode_local_api_key(row.api_key_secret_ref)
            profiles.append(
                ModelSettings(
                    id=row.id,
                    name=row.name,
                    provider=ProviderKind(row.provider),
                    model=row.model,
                    base_url=row.base_url,
                    api_key=api_key,
                    has_api_key=bool(api_key),
                    is_default=row.is_default,
                    timeout_seconds=row.timeout_seconds,
                    thinking=decode_thinking_setting(row.thinking),
                )
            )
        if profiles:
            return profiles
        return [model_settings_from_provider_config(provider_config_from_env())]

    def save(self, settings: ModelSettingsUpdate) -> ModelSettings:
        return self.save_profile(settings, profile_id=self.get().id, make_default=True)

    def save_profile(
        self,
        settings: ModelSettingsUpdate,
        profile_id: str | None = None,
        make_default: bool = False,
    ) -> ModelSettings:
        self.initialize()
        profiles = self.list_profiles()
        default_id = next(
            (profile.id for profile in profiles if profile.is_default),
            profiles[0].id,
        )
        target_id = profile_id or f"model-{uuid4().hex[:10]}"
        existing = next((profile for profile in profiles if profile.id == target_id), None)
        existing_api_key = existing.api_key if existing else None
        api_key = None if settings.clear_api_key else settings.api_key or existing_api_key
        saved = ModelSettings(
            id=target_id,
            name=settings.name or (existing.name if existing else "Custom model"),
            provider=settings.provider,
            model=settings.model,
            base_url=settings.base_url,
            api_key=api_key,
            has_api_key=bool(api_key),
            is_default=make_default or target_id == default_id,
            timeout_seconds=settings.timeout_seconds,
            thinking=settings.thinking,
        )
        now = datetime.now(UTC)
        values = {
            "id": target_id,
            "project_id": None,
            "name": saved.name,
            "provider": saved.provider.value,
            "model": saved.model,
            "base_url": saved.base_url,
            "api_key_secret_ref": encode_local_api_key(saved.api_key),
            "timeout_seconds": saved.timeout_seconds,
            "thinking": encode_thinking_setting(saved.thinking),
            "is_default": saved.is_default,
            "updated_at": now,
        }
        with self.engine.begin() as connection:
            stored_profile_ids = {
                row.id
                for row in connection.execute(
                    select(model_profiles_table.c.id).where(
                        model_profiles_table.c.project_id.is_(None)
                    )
                ).all()
            }
            if saved.is_default:
                connection.execute(
                    update(model_profiles_table)
                    .where(model_profiles_table.c.project_id.is_(None))
                    .values(is_default=False, updated_at=now)
                )
            for profile in profiles:
                if profile.id in stored_profile_ids or profile.id == target_id:
                    continue
                connection.execute(
                    insert(model_profiles_table).values(
                        id=profile.id,
                        project_id=None,
                        name=profile.name,
                        provider=profile.provider.value,
                        model=profile.model,
                        base_url=profile.base_url,
                        api_key_secret_ref=encode_local_api_key(profile.api_key),
                        timeout_seconds=profile.timeout_seconds,
                        thinking=encode_thinking_setting(profile.thinking),
                        is_default=(profile.id == default_id and not saved.is_default),
                        created_at=now,
                        updated_at=now,
                    )
                )
            existing_row = connection.execute(
                select(model_profiles_table.c.id).where(
                    model_profiles_table.c.id == target_id
                )
            ).one_or_none()
            if existing_row is None:
                connection.execute(insert(model_profiles_table).values(created_at=now, **values))
            else:
                connection.execute(
                    update(model_profiles_table)
                    .where(model_profiles_table.c.id == target_id)
                    .values(**values)
                )
        return saved

    def set_default(self, profile_id: str) -> ModelSettings | None:
        self.initialize()
        profiles = self.list_profiles()
        selected = next((profile for profile in profiles if profile.id == profile_id), None)
        if selected is None:
            return None
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            connection.execute(
                update(model_profiles_table)
                .where(model_profiles_table.c.project_id.is_(None))
                .values(is_default=False, updated_at=now)
            )
            connection.execute(
                update(model_profiles_table)
                .where(model_profiles_table.c.id == profile_id)
                .values(is_default=True, updated_at=now)
            )
        return self.get()

    def delete_profile(self, profile_id: str) -> ModelSettings | None:
        if profile_id == GLOBAL_MODEL_PROFILE_ID:
            return None
        self.initialize()
        profiles = self.list_profiles()
        selected = next((profile for profile in profiles if profile.id == profile_id), None)
        if selected is None or selected.is_default or len(profiles) <= 1:
            return None
        with self.engine.begin() as connection:
            connection.execute(
                delete(model_profiles_table).where(model_profiles_table.c.id == profile_id)
            )
        return self.get()

    def provider_config(self) -> ProviderConfig:
        settings = self.get()
        return model_settings_to_provider_config(settings)


class DatabaseKnowledgeStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        metadata.create_all(self.engine)

    def save_snapshot(self, snapshot: KnowledgeGraphSnapshot) -> None:
        self.initialize()
        project_id = snapshot.run.project_id
        with self.engine.begin() as connection:
            connection.execute(
                delete(knowledge_index_runs_table).where(
                    knowledge_index_runs_table.c.id == snapshot.run.id
                )
            )
            connection.execute(
                insert(knowledge_index_runs_table).values(
                    id=snapshot.run.id,
                    project_id=snapshot.run.project_id,
                    status=snapshot.run.status.value,
                    source_ref=snapshot.run.source_ref,
                    started_at=snapshot.run.started_at,
                    completed_at=snapshot.run.completed_at,
                    error_message=snapshot.run.error_message,
                    request_snapshot=snapshot.run.request.model_dump(mode="json"),
                    summary=snapshot.run.summary.model_dump(mode="json"),
                )
            )
            self._replace_graph(connection, project_id, snapshot)

    def get_index_run(self, run_id: str) -> KnowledgeIndexRun | None:
        self.initialize()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(knowledge_index_runs_table).where(knowledge_index_runs_table.c.id == run_id)
            ).one_or_none()
        return knowledge_index_run_from_row(row) if row else None

    def list_index_runs(self, project_id: str | None = None) -> list[KnowledgeIndexRun]:
        self.initialize()
        query = select(knowledge_index_runs_table).order_by(
            knowledge_index_runs_table.c.completed_at.desc(),
            knowledge_index_runs_table.c.started_at.desc(),
        )
        if project_id:
            query = query.where(knowledge_index_runs_table.c.project_id == project_id)
        with self.engine.begin() as connection:
            rows = connection.execute(query).all()
        return [knowledge_index_run_from_row(row) for row in rows]

    def search(self, request: KnowledgeSearchRequest) -> list[KnowledgeSearchResult]:
        self.initialize()
        nodes_query = select(knowledge_nodes_table)
        chunks_query = select(knowledge_chunks_table)
        if request.project_id is not None:
            nodes_query = nodes_query.where(
                knowledge_nodes_table.c.project_id == request.project_id
            )
            chunks_query = chunks_query.where(
                knowledge_chunks_table.c.project_id == request.project_id
            )
        with self.engine.begin() as connection:
            node_rows = connection.execute(nodes_query).all()
            chunk_rows = connection.execute(chunks_query).all()
        nodes = [knowledge_node_from_row(row) for row in node_rows]
        chunks = [knowledge_chunk_from_row(row) for row in chunk_rows]
        return score_knowledge_search(request, nodes, chunks)

    def document_refs(self, project_id: str | None = None) -> KnowledgeDocumentRefs:
        self.initialize()
        nodes_query = select(knowledge_nodes_table)
        chunks_query = select(knowledge_chunks_table)
        if project_id is not None:
            nodes_query = nodes_query.where(
                knowledge_nodes_table.c.project_id == project_id
            )
            chunks_query = chunks_query.where(
                knowledge_chunks_table.c.project_id == project_id
            )
        with self.engine.begin() as connection:
            node_rows = connection.execute(nodes_query).all()
            chunk_rows = connection.execute(chunks_query).all()
        nodes = [knowledge_node_from_row(row) for row in node_rows]
        chunks = [knowledge_chunk_from_row(row) for row in chunk_rows]
        return knowledge_document_refs(nodes, chunks, project_id=project_id)

    def tag_cloud(self, project_id: str | None = None) -> list[KnowledgeTag]:
        self.initialize()
        query = select(knowledge_nodes_table)
        if project_id is not None:
            query = query.where(knowledge_nodes_table.c.project_id == project_id)
        with self.engine.begin() as connection:
            rows = connection.execute(query).all()
        nodes = [knowledge_node_from_row(row) for row in rows]
        return knowledge_tag_cloud(nodes, project_id=project_id)

    def related_edges(
        self,
        node_ids: set[str],
        project_id: str | None = None,
    ) -> list[KnowledgeEdge]:
        self.initialize()
        if not node_ids:
            return []
        query = select(knowledge_edges_table).where(
            knowledge_edges_table.c.source_node_id.in_(node_ids)
            | knowledge_edges_table.c.target_node_id.in_(node_ids)
        )
        if project_id is not None:
            query = query.where(knowledge_edges_table.c.project_id == project_id)
        with self.engine.begin() as connection:
            rows = connection.execute(query).all()
        return [knowledge_edge_from_row(row) for row in rows]

    def _replace_graph(
        self,
        connection: Connection,
        project_id: str | None,
        snapshot: KnowledgeGraphSnapshot,
    ) -> None:
        node_scope = knowledge_nodes_table.c.project_id.is_(None)
        edge_scope = knowledge_edges_table.c.project_id.is_(None)
        chunk_scope = knowledge_chunks_table.c.project_id.is_(None)
        if project_id is not None:
            node_scope = knowledge_nodes_table.c.project_id == project_id
            edge_scope = knowledge_edges_table.c.project_id == project_id
            chunk_scope = knowledge_chunks_table.c.project_id == project_id
        connection.execute(delete(knowledge_chunks_table).where(chunk_scope))
        connection.execute(delete(knowledge_edges_table).where(edge_scope))
        connection.execute(delete(knowledge_nodes_table).where(node_scope))
        for node in snapshot.nodes:
            connection.execute(insert(knowledge_nodes_table).values(**node.model_dump(mode="python")))
        for edge in snapshot.edges:
            connection.execute(insert(knowledge_edges_table).values(**edge.model_dump(mode="python")))
        for chunk in snapshot.chunks:
            connection.execute(
                insert(knowledge_chunks_table).values(**chunk.model_dump(mode="python"))
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


def create_project_profile_store() -> ProjectProfileStore:
    database_url = os.environ.get("GUIDESYNC_DATABASE_URL")
    if database_url:
        return DatabaseProjectProfileStore(database_url)
    return FileProjectProfileStore()


def create_model_settings_store() -> ModelSettingsStore:
    database_url = os.environ.get("GUIDESYNC_DATABASE_URL")
    if database_url:
        return DatabaseModelSettingsStore(database_url)
    return FileModelSettingsStore()


def create_knowledge_store() -> KnowledgeStore:
    database_url = os.environ.get("GUIDESYNC_DATABASE_URL")
    if database_url:
        return DatabaseKnowledgeStore(database_url)
    return FileKnowledgeStore()


def initialize_storage() -> None:
    create_run_store().initialize()
    create_project_store().initialize()
    create_project_profile_store().initialize()
    create_model_settings_store().initialize()
    create_knowledge_store().initialize()


def run_result_from_snapshot(snapshot: str | dict[str, object]) -> GuideSyncRunResult:
    payload = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
    request = payload.get("request")
    if isinstance(request, dict):
        request_payload = cast(dict[str, Any], request)
        audience = request.get("audience")
        if isinstance(audience, str):
            request_payload["audience"] = legacy_audience_alias(audience)
    return GuideSyncRunResult.model_validate(payload)


def legacy_audience_alias(value: str) -> str:
    aliases = {
        "product users": Audience.END_USERS.value,
        "ordinary product users": Audience.END_USERS.value,
        "end users": Audience.END_USERS.value,
        "documentation reviewer": Audience.DEVELOPERS.value,
    }
    return aliases.get(value, value)


def model_settings_to_provider_config(settings: ModelSettings) -> ProviderConfig:
    return ProviderConfig(
        provider=settings.provider,
        model=settings.model,
        name=settings.name,
        base_url=settings.base_url,
        api_key=settings.api_key,
        timeout_seconds=settings.timeout_seconds,
        thinking=settings.thinking,
        metadata={"model_profile_id": settings.id},
    )


def effective_model_configuration_from_provider_config(
    config: ProviderConfig,
) -> EffectiveModelConfiguration:
    return EffectiveModelConfiguration(
        model_profile_id=config.metadata.get("model_profile_id"),
        name=config.name,
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        thinking=config.thinking,
        metadata=config.metadata,
    )


def model_settings_from_provider_config(config: ProviderConfig) -> ModelSettings:
    return ModelSettings(
        id=config.metadata.get("model_profile_id", GLOBAL_MODEL_PROFILE_ID),
        name=config.name or "Default model",
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        has_api_key=bool(config.api_key),
        is_default=True,
        timeout_seconds=config.timeout_seconds,
        thinking=config.thinking,
    )


def encode_local_api_key(api_key: str | None) -> str | None:
    return f"local-inline:{api_key}" if api_key else None


def decode_local_api_key(secret_ref: str | None) -> str | None:
    if not secret_ref:
        return None
    if secret_ref.startswith("local-inline:"):
        return secret_ref.removeprefix("local-inline:")
    return None


def encode_thinking_setting(thinking: ThinkingSetting | None) -> str | None:
    if thinking is None:
        return None
    if isinstance(thinking, bool):
        return "true" if thinking else "false"
    return thinking


def decode_thinking_setting(value: str | None) -> ThinkingSetting | None:
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    return cast(ThinkingSetting, value)


def project_profile_from_row(row: Row) -> ProjectProfileSnapshot:
    mapping = row._mapping
    return ProjectProfileSnapshot(
        id=mapping["id"],
        project_id=mapping["project_id"],
        status=ProjectProfileStatus(mapping["status"]),
        version=mapping["version"],
        prompt_version=mapping["prompt_version"],
        summary=mapping["summary"],
        architecture=list(mapping["architecture"]),
        workflows=list(mapping["workflows"]),
        key_terms=list(mapping["key_terms"]),
        repository_map=[
            ProjectProfileRepositoryMapItem.model_validate(item)
            for item in mapping["repository_map"]
        ],
        source_refs=[
            ProjectProfileSourceRef.model_validate(item) for item in mapping["source_refs"]
        ],
        warnings=list(mapping["warnings"]),
        uncertainty_notes=list(mapping["uncertainty_notes"]),
        artifact_uris=dict(mapping["artifact_uris"]),
        created_at=mapping["created_at"],
        completed_at=mapping["completed_at"],
        error_message=mapping["error_message"],
    )


def knowledge_index_run_from_row(row: Row) -> KnowledgeIndexRun:
    mapping = row._mapping
    return KnowledgeIndexRun(
        id=mapping["id"],
        project_id=mapping["project_id"],
        status=KnowledgeIndexStatus(mapping["status"]),
        source_ref=mapping["source_ref"],
        started_at=mapping["started_at"],
        completed_at=mapping["completed_at"],
        error_message=mapping["error_message"],
        request=KnowledgeIndexRequest.model_validate(mapping["request_snapshot"]),
        summary=KnowledgeIndexSummary.model_validate(mapping["summary"]),
    )


def knowledge_node_from_row(row: Row) -> KnowledgeNode:
    mapping = row._mapping
    return KnowledgeNode(
        id=mapping["id"],
        project_id=mapping["project_id"],
        repo=mapping["repo"],
        kind=mapping["kind"],
        name=mapping["name"],
        qualified_name=mapping["qualified_name"],
        path=mapping["path"],
        start_line=mapping["start_line"],
        end_line=mapping["end_line"],
        summary=mapping["summary"],
        content_hash=mapping["content_hash"],
        metadata=mapping["metadata"],
        created_at=mapping["created_at"],
    )


def knowledge_edge_from_row(row: Row) -> KnowledgeEdge:
    mapping = row._mapping
    return KnowledgeEdge(
        id=mapping["id"],
        project_id=mapping["project_id"],
        source_node_id=mapping["source_node_id"],
        target_node_id=mapping["target_node_id"],
        edge_type=mapping["edge_type"],
        confidence=mapping["confidence"],
        evidence_ref=mapping["evidence_ref"],
        metadata=mapping["metadata"],
        created_at=mapping["created_at"],
    )


def knowledge_chunk_from_row(row: Row) -> KnowledgeChunk:
    mapping = row._mapping
    return KnowledgeChunk(
        id=mapping["id"],
        project_id=mapping["project_id"],
        node_id=mapping["node_id"],
        repo=mapping["repo"],
        path=mapping["path"],
        heading=mapping["heading"],
        text=mapping["text"],
        token_count=mapping["token_count"],
        metadata=mapping["metadata"],
        created_at=mapping["created_at"],
    )


def score_knowledge_search(
    request: KnowledgeSearchRequest,
    nodes: list[KnowledgeNode],
    chunks: list[KnowledgeChunk],
) -> list[KnowledgeSearchResult]:
    node_by_id = {node.id: node for node in nodes}
    results: list[KnowledgeSearchResult] = []
    for node in nodes:
        if not node_matches_filters(node, request):
            continue
        score = score_knowledge_text(
            request.query,
            " ".join(
                item
                for item in [node.name, node.qualified_name, node.path, node.summary]
                if item
            )
            + " "
            + searchable_knowledge_metadata(node.metadata),
        )
        if score > 0:
            results.append(
                KnowledgeSearchResult(
                    node=node,
                    chunk=None,
                    score=score,
                    matched_text=trim_excerpt(node.summary or node.qualified_name, request.query),
                )
            )
    for chunk in chunks:
        node = node_by_id.get(chunk.node_id)
        if node is None or not node_matches_filters(node, request):
            continue
        score = score_knowledge_text(
            request.query,
            " ".join(item for item in [chunk.heading, chunk.path, chunk.text] if item)
            + " "
            + searchable_knowledge_metadata(chunk.metadata),
        )
        if score > 0:
            results.append(
                KnowledgeSearchResult(
                    node=node,
                    chunk=chunk,
                    score=score,
                    matched_text=trim_excerpt(chunk.text, request.query),
                )
            )
    return sorted(
        results,
        key=lambda result: (
            result.score,
            result.node.kind,
            result.node.path or "",
            result.node.name,
        ),
        reverse=True,
    )[: request.limit]


def knowledge_document_refs(
    nodes: list[KnowledgeNode],
    chunks: list[KnowledgeChunk],
    *,
    project_id: str | None = None,
) -> KnowledgeDocumentRefs:
    scoped_nodes = [
        node for node in nodes if project_id is None or node.project_id == project_id
    ]
    docs = [node for node in scoped_nodes if node.kind == "doc_page" and node.path]
    sections = [
        node for node in scoped_nodes if node.kind == "doc_section" and node.path
    ]
    chunks_by_node = {chunk.node_id: chunk for chunk in chunks}
    document_id_by_path = {doc.path: doc.id for doc in docs if doc.path}
    section_counts = Counter(section.path for section in sections if section.path)
    document_refs = [
        KnowledgeDocumentRef(
            id=doc.id,
            project_id=doc.project_id,
            repo=doc.repo,
            path=doc.path or "",
            title=doc.name,
            summary=doc.summary,
            content_hash=doc.content_hash,
            source_commit=string_metadata(doc.metadata, "commit_sha"),
            tags=list_metadata(doc.metadata, "tags"),
            categories=list_metadata(doc.metadata, "categories"),
            search_terms=list_metadata(doc.metadata, "search_terms"),
            section_count=section_counts.get(doc.path, 0),
        )
        for doc in sorted(docs, key=lambda item: (item.path or "", item.name))
    ]
    section_refs = []
    for section in sorted(
        sections,
        key=lambda item: (item.path or "", item.start_line or 0, item.name),
    ):
        if section.path is None:
            continue
        document_id = document_id_by_path.get(section.path)
        if document_id is None:
            continue
        chunk = chunks_by_node.get(section.id)
        metadata = {**section.metadata, **(chunk.metadata if chunk else {})}
        section_refs.append(
            KnowledgeSectionRef(
                id=section.id,
                project_id=section.project_id,
                document_id=document_id,
                repo=section.repo,
                path=section.path,
                heading=section.name,
                start_line=section.start_line,
                end_line=section.end_line,
                summary=section.summary,
                content_hash=section.content_hash,
                source_commit=string_metadata(metadata, "commit_sha"),
                tags=list_metadata(metadata, "tags"),
                categories=list_metadata(metadata, "categories"),
                search_terms=list_metadata(metadata, "search_terms"),
            )
        )
    return KnowledgeDocumentRefs(documents=document_refs, sections=section_refs)


def knowledge_tag_cloud(
    nodes: list[KnowledgeNode],
    *,
    project_id: str | None = None,
) -> list[KnowledgeTag]:
    tags: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    for node in nodes:
        if project_id is not None and node.project_id != project_id:
            continue
        tags.update(list_metadata(node.metadata, "tags"))
        categories.update(list_metadata(node.metadata, "categories"))
    values = [
        KnowledgeTag(value=value, count=count, category="tag")
        for value, count in tags.items()
    ]
    values.extend(
        KnowledgeTag(value=value, count=count, category="category")
        for value, count in categories.items()
    )
    return sorted(values, key=lambda item: (item.count, item.value), reverse=True)


def list_metadata(metadata: dict[str, object], key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def string_metadata(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def node_matches_filters(node: KnowledgeNode, request: KnowledgeSearchRequest) -> bool:
    if request.project_id is not None and node.project_id != request.project_id:
        return False
    if request.kinds and node.kind not in request.kinds:
        return False
    if request.path_prefixes:
        path = node.path or ""
        return any(path.startswith(prefix) for prefix in request.path_prefixes)
    return True


def score_knowledge_text(query: str, text: str) -> float:
    query_text = query.strip()
    query_lower = query_text.lower()
    target_lower = text.lower()
    terms = tokenize_text(query_text)
    if not terms:
        return 0.0
    target_terms = Counter(tokenize_text(text))
    score = 0.0
    if query_lower in target_lower:
        score += 4.0
    for term in terms:
        score += target_terms[term]
    return score


def searchable_knowledge_metadata(metadata: dict[str, object]) -> str:
    values: list[str] = []
    for key in ("tags", "categories", "search_terms"):
        value = metadata.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    return " ".join(values)


def trim_excerpt(text: str, query: str, limit: int = 320) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    index = compact.lower().find(query.lower().strip())
    if index < 0:
        return f"{compact[: limit - 1]}..."
    start = max(index - 80, 0)
    end = min(start + limit - 1, len(compact))
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(compact) else ""
    return f"{prefix}{compact[start:end]}{suffix}"


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
    connection: Connection,
    result: GuideSyncRunResult,
    now: datetime,
    created_at: datetime,
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
    effective_model_configuration = (
        result.request.effective_model_configuration
        or effective_model_configuration_from_provider_config(result.request.provider)
    )
    existing = connection.execute(
        select(report_runs_table.c.id).where(report_runs_table.c.id == result.run_id)
    ).one_or_none()
    values = {
        "id": result.run_id,
        "project_id": project_id_from_run_id(result.run_id),
        "status": result.status,
        "mode": None,
        "goal": result.request.goal,
        "audience": result.request.audience.value,
        "model_profile_id": effective_model_configuration.model_profile_id,
        "provider": provider.value if hasattr(provider, "value") else provider,
        "model": model,
        "task_interface_url": result.request.task_interface_url,
        "screenshot_policy": result.request.screenshot_policy.value,
        "requested_model_settings": (
            result.request.requested_model_settings.model_dump(mode="json")
            if result.request.requested_model_settings
            else None
        ),
        "effective_model_configuration": effective_model_configuration.model_dump(mode="json"),
        "project_profile_snapshot_id": result.request.project_profile_snapshot_id,
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


def replace_run_artifacts(
    connection: Connection,
    result: GuideSyncRunResult,
    now: datetime,
) -> None:
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
