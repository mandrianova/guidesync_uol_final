from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection

from guidesync_agent.config import provider_config_from_settings
from guidesync_agent.models import (
    model_profiles_table,
)
from guidesync_agent.schemas import (
    ModelRole,
    ModelSettings,
    ModelSettingsUpdate,
    ProviderConfig,
    ProviderKind,
)

from .config import GLOBAL_MODEL_PROFILE_ID
from .database_engine import DatabaseEngineInput, resolve_database_engine
from .serialization import (
    decode_local_api_key,
    decode_model_roles,
    decode_thinking_setting,
    encode_local_api_key,
    encode_model_roles,
    encode_thinking_setting,
    model_profile_roles_from_update,
    model_settings_from_provider_config,
    model_settings_to_provider_config,
    remove_model_profile_roles,
)


class DatabaseModelSettingsStore:
    def __init__(self, database: DatabaseEngineInput) -> None:
        self.engine = resolve_database_engine(database)

    def initialize(self) -> None:
        return None

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
                    max_concurrent_agents=row.max_concurrent_agents,
                    thinking=decode_thinking_setting(row.thinking),
                    roles=decode_model_roles(row.roles),
                )
            )
        if profiles:
            return profiles
        return [model_settings_from_provider_config(provider_config_from_settings())]

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
        roles = model_profile_roles_from_update(settings, existing)
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
            max_concurrent_agents=settings.max_concurrent_agents,
            thinking=settings.thinking,
            roles=roles,
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
            "max_concurrent_agents": saved.max_concurrent_agents,
            "thinking": encode_thinking_setting(saved.thinking),
            "roles": encode_model_roles(saved.roles),
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
            self._remove_assigned_roles(connection, saved.roles, target_id, now)
            for profile in profiles:
                if profile.id in stored_profile_ids or profile.id == target_id:
                    continue
                profile_without_assigned_roles = remove_model_profile_roles(profile, saved.roles)
                connection.execute(
                    insert(model_profiles_table).values(
                        id=profile_without_assigned_roles.id,
                        project_id=None,
                        name=profile_without_assigned_roles.name,
                        provider=profile_without_assigned_roles.provider.value,
                        model=profile_without_assigned_roles.model,
                        base_url=profile_without_assigned_roles.base_url,
                        api_key_secret_ref=encode_local_api_key(
                            profile_without_assigned_roles.api_key
                        ),
                        timeout_seconds=profile_without_assigned_roles.timeout_seconds,
                        max_concurrent_agents=(
                            profile_without_assigned_roles.max_concurrent_agents
                        ),
                        thinking=encode_thinking_setting(profile_without_assigned_roles.thinking),
                        roles=encode_model_roles(profile_without_assigned_roles.roles),
                        is_default=(
                            profile_without_assigned_roles.id == default_id
                            and not saved.is_default
                        ),
                        created_at=now,
                        updated_at=now,
                    )
                )
            existing_row = connection.execute(
                select(model_profiles_table.c.id).where(model_profiles_table.c.id == target_id)
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

    def _remove_assigned_roles(
        self,
        connection: Connection,
        assigned_roles: list[ModelRole],
        target_id: str,
        updated_at: datetime,
    ) -> None:
        if not assigned_roles:
            return
        for row in connection.execute(
            select(model_profiles_table.c.id, model_profiles_table.c.roles).where(
                model_profiles_table.c.project_id.is_(None),
                model_profiles_table.c.id != target_id,
            )
        ).all():
            current_roles = decode_model_roles(row.roles)
            next_roles = [
                role
                for role in current_roles
                if role not in assigned_roles
            ]
            if next_roles == current_roles:
                continue
            connection.execute(
                update(model_profiles_table)
                .where(model_profiles_table.c.id == row.id)
                .values(roles=encode_model_roles(next_roles), updated_at=updated_at)
            )

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
