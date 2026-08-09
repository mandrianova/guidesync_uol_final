from __future__ import annotations

import os
from io import BytesIO
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError
from project_profile_fake_agent import run_fake_project_profile_agent
from storage_test_utils import sqlite_database_url

from guidesync_agent import reports
from guidesync_agent.agent_runtime import project_profile as project_profile_agent_runtime


@pytest.fixture(autouse=True)
def use_isolated_unit_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", sqlite_database_url(tmp_path / "guidesync.db"))
    monkeypatch.delenv("GUIDESYNC_PROJECT_PROFILE_AGENT_PROVIDER", raising=False)
    monkeypatch.setenv("GUIDESYNC_CODE_CHANGE_ANALYSIS_PROVIDER", "deterministic")
    monkeypatch.setenv("GUIDESYNC_SCREENSHOT_VISION_PROVIDER", "deterministic_test")
    monkeypatch.setenv("GUIDESYNC_SEMANTIC_RANKER_MODE", "deterministic_test")
    monkeypatch.delenv("GUIDESYNC_REPOSITORY_SYNC_QUEUE_NAME", raising=False)
    monkeypatch.delenv("GUIDESYNC_REPOSITORY_SYNC_QUEUE_URL", raising=False)
    monkeypatch.delenv("GUIDESYNC_SQS_ENDPOINT_URL", raising=False)

    monkeypatch.setattr(
        project_profile_agent_runtime,
        "run_pydantic_agent_sync",
        run_fake_project_profile_agent,
    )
    if os.environ.get("GUIDESYNC_RUN_COMPOSE_E2E") == "1":
        monkeypatch.setenv("GUIDESYNC_S3_BUCKET", "guidesync-reports")
        monkeypatch.setenv("GUIDESYNC_S3_ENDPOINT_URL", "http://minio:9000")
        monkeypatch.setenv("GUIDESYNC_S3_PREFIX", "tests")
    else:
        monkeypatch.setenv("GUIDESYNC_S3_BUCKET", "guidesync-test-artifacts")
        monkeypatch.setenv("GUIDESYNC_S3_PREFIX", "tests")
        install_test_s3(monkeypatch)


def install_test_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    objects: dict[tuple[str, str], tuple[bytes, str | None]] = {}

    class TestS3Client:
        def put_object(self, **kwargs: object) -> None:
            body = kwargs["Body"]
            if isinstance(body, str):
                payload = body.encode()
            elif isinstance(body, (bytes, bytearray)):
                payload = bytes(body)
            else:
                raise TypeError("Test S3 body must be bytes or text.")
            key = (str(kwargs["Bucket"]), str(kwargs["Key"]))
            content_type = kwargs.get("ContentType")
            objects[key] = (payload, str(content_type) if content_type else None)

        def get_object(self, **kwargs: object) -> dict[str, object]:
            key = (str(kwargs["Bucket"]), str(kwargs["Key"]))
            if key not in objects:
                raise ClientError(
                    {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                    "GetObject",
                )
            payload, content_type = objects[key]
            return {"Body": BytesIO(payload), "ContentType": content_type}

    client = TestS3Client()
    monkeypatch.setattr(
        reports,
        "boto3",
        SimpleNamespace(client=lambda *_, **__: client),
    )
