from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from guidesync_agent.settings import get_settings

LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
LOG_FILE_BACKUP_COUNT = 3


class GuideSyncRotatingFileHandler(RotatingFileHandler):
    pass


def configure_logging() -> None:
    paths = get_settings().paths
    log_dir = paths.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if any(isinstance(handler, GuideSyncRotatingFileHandler) for handler in root.handlers):
        return
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    full_log_handler = create_rotating_handler(
        log_dir / f"{paths.log_name}.log",
        level=logging.INFO,
        formatter=formatter,
    )
    error_log_handler = create_rotating_handler(
        log_dir / f"{paths.log_name}-errors.log",
        level=logging.ERROR,
        formatter=formatter,
    )
    root.addHandler(full_log_handler)
    root.addHandler(error_log_handler)
    if not any(type(handler) is logging.StreamHandler for handler in root.handlers):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)


def create_rotating_handler(
    path: Path,
    *,
    level: int,
    formatter: logging.Formatter,
) -> GuideSyncRotatingFileHandler:
    handler = GuideSyncRotatingFileHandler(
        path,
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler
