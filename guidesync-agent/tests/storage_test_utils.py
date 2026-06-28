from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine

from guidesync_agent.models import metadata


def sqlite_database_url(path: Path) -> str:
    database_url = f"sqlite+pysqlite:///{path}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    engine.dispose()
    return database_url
