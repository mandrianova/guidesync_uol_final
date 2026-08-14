from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import create_engine, delete, insert, select, update

from guidesync_agent.models import (
    project_documentation_table,
    project_profiles_table,
    project_repositories_table,
    projects_table,
)
from guidesync_agent.schemas import (
    Audience,
    ProjectConfig,
    ProjectCreate,
    ProjectDocumentation,
    ProjectProfileSnapshot,
    ProjectRepository,
    RepositoryCacheStatus,
    TaskInterfaceAuthType,
    TaskInterfaceAuthUpdate,
)

from .serialization import (
    project_profile_from_row,
)


class DatabaseProjectStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        return None

    def list_projects(self) -> list[ProjectConfig]:
        self.initialize()
        with self.engine.begin() as connection:
            rows = connection.execute(select(projects_table).order_by(projects_table.c.name)).all()
        return [project for row in rows if (project := self.get(row.id)) is not None]

    def save(self, project: ProjectCreate, project_id: str | None = None) -> ProjectConfig:
        self.initialize()
        now = datetime.now(UTC)
        existing = self.get(project_id) if project_id else None
        auth_type = existing.task_interface_auth_type if existing else None
        auth_secret = existing.task_interface_auth_secret if existing else None
        if project.task_interface_auth_update is TaskInterfaceAuthUpdate.REPLACE:
            auth_type = project.task_interface_auth_type
            auth_secret = project.task_interface_auth_secret
        elif project.task_interface_auth_update is TaskInterfaceAuthUpdate.REMOVE:
            auth_type = None
            auth_secret = None
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
            task_interface_url=project.task_interface_url,
            task_interface_auth_type=auth_type,
            has_task_interface_auth=auth_secret is not None,
            task_interface_auth_secret=auth_secret,
            repositories=project.repositories,
            documentation=project.documentation,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        with self.engine.begin() as connection:
            project_values = {
                "id": saved.id,
                "name": saved.name,
                "description": saved.description,
                "audience": saved.audience.value,
                "documentation_instructions": saved.documentation_instructions,
                "knowledge_base_repository_id": saved.knowledge_base_repository_id,
                "knowledge_base_ref": saved.knowledge_base_ref,
                "knowledge_base_path": saved.knowledge_base_path,
                "analysis_paths": saved.analysis_paths,
                "credential_ref": saved.credential_ref,
                "task_interface_url": saved.task_interface_url,
                "task_interface_auth_type": auth_type.value if auth_type is not None else None,
                "task_interface_auth_secret": (
                    auth_secret.get_secret_value() if auth_secret is not None else None
                ),
                "created_at": saved.created_at,
                "updated_at": saved.updated_at,
            }
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
            if existing:
                connection.execute(
                    update(projects_table)
                    .where(projects_table.c.id == saved.id)
                    .values(**project_values)
                )
            else:
                connection.execute(insert(projects_table).values(**project_values))
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
            task_interface_url=project_row.task_interface_url,
            task_interface_auth_type=(
                TaskInterfaceAuthType(project_row.task_interface_auth_type)
                if project_row.task_interface_auth_type is not None
                else None
            ),
            has_task_interface_auth=project_row.task_interface_auth_secret is not None,
            task_interface_auth_secret=(
                SecretStr(project_row.task_interface_auth_secret)
                if project_row.task_interface_auth_secret is not None
                else None
            ),
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
        return None

    def save(self, profile: ProjectProfileSnapshot) -> ProjectProfileSnapshot:
        self.initialize()
        values = {
            "id": profile.id,
            "project_id": profile.project_id,
            "status": profile.status.value,
            "version": profile.version,
            "prompt_version": profile.prompt_version,
            "summary": profile.summary,
            "project_description": profile.project_description,
            "project_structure": profile.project_structure,
            "architecture": profile.architecture,
            "core_concepts": profile.core_concepts,
            "workflows": profile.workflows,
            "key_terms": profile.key_terms,
            "agent_context": profile.agent_context,
            "taxonomy": profile.taxonomy.model_dump(mode="json"),
            "profile_evidence": [item.model_dump(mode="json") for item in profile.profile_evidence],
            "repository_map": [item.model_dump(mode="json") for item in profile.repository_map],
            "source_refs": [item.model_dump(mode="json") for item in profile.source_refs],
            "warnings": profile.warnings,
            "uncertainty_notes": profile.uncertainty_notes,
            "artifact_uris": profile.artifact_uris,
            "model_metadata": profile.model_metadata,
            "tool_trace_refs": profile.tool_trace_refs,
            "validation_findings": [
                item.model_dump(mode="json") for item in profile.validation_findings
            ],
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
