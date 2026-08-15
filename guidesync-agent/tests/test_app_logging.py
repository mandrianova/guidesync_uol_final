from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from guidesync_agent.app_logging import (
    LOG_FILE_BACKUP_COUNT,
    LOG_FILE_MAX_BYTES,
    GuideSyncRotatingFileHandler,
    configure_logging,
)


def test_configure_logging_creates_component_full_and_error_logs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("GUIDESYNC_LOG_NAME", "test-worker")
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    root.handlers = []

    try:
        configure_logging()
        configure_logging()
        logging.getLogger("guidesync-test").info("ordinary runtime detail")
        logging.getLogger("guidesync-test").error("diagnostic failure")
        managed_handlers = [
            handler
            for handler in root.handlers
            if isinstance(handler, GuideSyncRotatingFileHandler)
        ]
        for handler in managed_handlers:
            handler.flush()

        assert len(managed_handlers) == 2
        assert all(isinstance(handler, RotatingFileHandler) for handler in managed_handlers)
        assert all(handler.maxBytes == LOG_FILE_MAX_BYTES for handler in managed_handlers)
        assert all(handler.backupCount == LOG_FILE_BACKUP_COUNT for handler in managed_handlers)
        assert "ordinary runtime detail" in (tmp_path / "test-worker.log").read_text()
        error_log = (tmp_path / "test-worker-errors.log").read_text()
        assert "diagnostic failure" in error_log
        assert "ordinary runtime detail" not in error_log
    finally:
        for handler in root.handlers:
            if isinstance(handler, GuideSyncRotatingFileHandler):
                handler.close()
        root.handlers = original_handlers
        root.setLevel(original_level)
