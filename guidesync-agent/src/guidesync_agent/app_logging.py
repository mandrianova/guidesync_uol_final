from __future__ import annotations

import logging
import sys

from guidesync_agent.settings import get_settings


def configure_logging() -> None:
    log_dir = get_settings().paths.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "guidesync-agent.log"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if any(isinstance(handler, logging.FileHandler) for handler in root.handlers):
        return
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    if not any(type(handler) is logging.StreamHandler for handler in root.handlers):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
