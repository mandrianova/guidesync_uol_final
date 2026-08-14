from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url

POSTGRES_POOL_SIZE = 5
POSTGRES_MAX_OVERFLOW = 5
POSTGRES_POOL_TIMEOUT_SECONDS = 30
DATABASE_ENGINE_CACHE_SIZE = 8

DatabaseEngineInput = str | Engine


@lru_cache(maxsize=DATABASE_ENGINE_CACHE_SIZE)
def create_database_engine(database_url: str) -> Engine:
    if make_url(database_url).get_backend_name() == "postgresql":
        return create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=POSTGRES_POOL_SIZE,
            max_overflow=POSTGRES_MAX_OVERFLOW,
            pool_timeout=POSTGRES_POOL_TIMEOUT_SECONDS,
        )
    return create_engine(database_url, pool_pre_ping=True)


def resolve_database_engine(database: DatabaseEngineInput) -> Engine:
    if isinstance(database, str):
        return create_database_engine(database)
    return database
