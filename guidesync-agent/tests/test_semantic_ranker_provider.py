from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from guidesync_agent.schemas import ModelRole, ProviderKind, TokenUsageSource
from guidesync_agent.services.knowledge_annotation.providers import (
    DeterministicSemanticRanker,
    LocalEmbeddingEndpointRanker,
    default_semantic_ranker,
)
from guidesync_agent.storage import DatabaseModelUsageStore


class EmbeddingHandler(BaseHTTPRequestHandler):
    status_code = 200
    invalid_payload = False
    requests: list[dict[str, Any]] = []

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        self.requests.append(payload)
        if self.status_code != 200:
            self.send_response(self.status_code)
            self.end_headers()
            self.wfile.write(b'{"error":"embedding unavailable"}')
            return
        if self.invalid_payload:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data":[{"missing_embedding":true}]}')
            return
        inputs = payload["input"]
        body = {
            "data": [
                {"embedding": [1.0, 0.0] if index == 0 else [1.0, float(index)]}
                for index, _ in enumerate(inputs)
            ],
            "usage": {
                "prompt_tokens": len(inputs) * 3,
                "total_tokens": len(inputs) * 3,
            },
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        return None


@contextmanager
def embedding_server(*, status_code: int = 200, invalid_payload: bool = False) -> Iterator[str]:
    EmbeddingHandler.status_code = status_code
    EmbeddingHandler.invalid_payload = invalid_payload
    EmbeddingHandler.requests = []
    server = HTTPServer(("127.0.0.1", 0), EmbeddingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_default_semantic_ranker_uses_configured_embedding_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    with embedding_server() as base_url:
        monkeypatch.setenv("GUIDESYNC_SEMANTIC_RANKER_MODE", "embedding_endpoint")
        monkeypatch.setenv("GUIDESYNC_EMBEDDING_BASE_URL", base_url)
        monkeypatch.setenv("GUIDESYNC_EMBEDDING_MODEL", "local-fixture-embedding")

        ranker = default_semantic_ranker(warnings)
        scores = ranker.rank("billing settings", ["billing settings", "release notes"])

    assert isinstance(ranker, LocalEmbeddingEndpointRanker)
    assert ranker.method_id == "local-embedding-endpoint:local-fixture-embedding"
    assert warnings == []
    assert scores["billing settings"] > scores["release notes"]
    assert EmbeddingHandler.requests[0]["model"] == "local-fixture-embedding"


def test_embedding_endpoint_ranker_records_model_usage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'embedding-usage.db'}"
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    with embedding_server() as base_url:
        ranker = LocalEmbeddingEndpointRanker(base_url, "local-fixture-embedding")
        ranker.set_usage_context(
            project_id="project-embedding",
            run_id="run-embedding",
            workflow_task_id="workflow-embedding",
            source_id="source-embedding",
        )

        scores = ranker.rank("billing settings", ["billing settings", "release notes"])

    entries = DatabaseModelUsageStore(database_url).list_for_run("run-embedding")
    assert scores["billing settings"] > scores["release notes"]
    assert ranker.warnings == []
    assert len(entries) == 1
    assert entries[0].role == ModelRole.EMBEDDING_RANKER
    assert entries[0].workflow_task_id == "workflow-embedding"
    assert entries[0].provider == ProviderKind.LOCAL_HTTP
    assert entries[0].usage_source == TokenUsageSource.PROVIDER_REPORTED
    assert entries[0].usage.embedding_input_tokens == 9


def test_default_semantic_ranker_raises_when_endpoint_is_unusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with embedding_server(status_code=500) as base_url:
        monkeypatch.setenv("GUIDESYNC_SEMANTIC_RANKER_MODE", "embedding_endpoint")
        monkeypatch.setenv("GUIDESYNC_EMBEDDING_BASE_URL", base_url)
        monkeypatch.setenv("GUIDESYNC_EMBEDDING_MODEL", "local-fixture-embedding")

        with pytest.raises(RuntimeError, match="GUIDESYNC_EMBEDDING_BASE_URL"):
            default_semantic_ranker([])


def test_default_semantic_ranker_requires_endpoint_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GUIDESYNC_SEMANTIC_RANKER_MODE", "embedding_endpoint")
    monkeypatch.delenv("GUIDESYNC_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.setenv("GUIDESYNC_EMBEDDING_MODEL", "local-fixture-embedding")

    with pytest.raises(RuntimeError, match="GUIDESYNC_EMBEDDING_BASE_URL"):
        default_semantic_ranker([])


def test_default_semantic_ranker_allows_explicit_deterministic_test_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setenv("GUIDESYNC_SEMANTIC_RANKER_MODE", "deterministic_test")
    monkeypatch.delenv("GUIDESYNC_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("GUIDESYNC_EMBEDDING_MODEL", raising=False)

    ranker = default_semantic_ranker(warnings)

    assert isinstance(ranker, DeterministicSemanticRanker)
    assert any("deterministic_test" in warning for warning in warnings)
