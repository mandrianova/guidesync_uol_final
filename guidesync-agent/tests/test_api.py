from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from guidesync_agent.api import app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "fixtures/domain-guide-task.json"


def load_fixture(tmp_path: Path) -> dict:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["run_id"] = "pytest-api-domain-guide"
    payload["report"]["output_dir"] = str(tmp_path / "api-run")
    return payload


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "guidesync-agent"}


def test_create_and_get_run(tmp_path: Path) -> None:
    client = TestClient(app)

    create_response = client.post("/runs", json=load_fixture(tmp_path))

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["run_id"] == "pytest-api-domain-guide"
    assert created["status"] == "completed"
    assert created["update"]["title"] == "Custom domain guide update"
    assert Path(created["artifacts"]["report.md"]).exists()

    get_response = client.get("/runs/pytest-api-domain-guide")

    assert get_response.status_code == 200
    assert get_response.json()["run_id"] == "pytest-api-domain-guide"
