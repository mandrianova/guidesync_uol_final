from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

from guidesync_agent.schemas import (
    ModelRole,
    ScreenshotCaptureResult,
)
from guidesync_agent.services.screenshot_validation import validate_screenshot_capture


class RecordingHTTPServer(ThreadingHTTPServer):
    requests: list[dict[str, Any]]

    def __init__(self, server_address: tuple[str, int]) -> None:
        super().__init__(server_address, VisionHandler)
        self.requests = []


class VisionHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        server = cast(RecordingHTTPServer, self.server)
        server.requests.append(payload)
        content = json.dumps(
            {
                "visible_text": "Document workflow screenshots",
                "page_summary": "GuideSync workflow page",
                "ui_state": "loaded",
                "confidence": 0.91,
                "warnings": [],
            }
        )
        response = {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        _ = (format, args)
        return


def test_default_screenshot_vision_adapter_uses_openai_compatible_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    server = RecordingHTTPServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("GUIDESYNC_SCREENSHOT_VISION_PROVIDER", "local_http")
        monkeypatch.setenv(
            "GUIDESYNC_SCREENSHOT_VISION_BASE_URL",
            f"http://127.0.0.1:{server.server_port}/v1",
        )
        monkeypatch.setenv("GUIDESYNC_SCREENSHOT_VISION_MODEL", "gemini-3.5-flash")
        screenshot = tmp_path / "screen.png"
        screenshot.write_bytes(b"\x89PNG\r\n\x1a\n")
        attempt = validate_screenshot_capture(
            ScreenshotCaptureResult(
                scenario="task-interface",
                url="http://127.0.0.1:5173/#/knowledge",
                path=str(screenshot),
                visible_text="Document workflow",
                blank=False,
            ),
            ["workflow"],
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert attempt.model_role == ModelRole.SCREENSHOT_VISION
    assert attempt.provider == "local_http"
    assert attempt.model == "gemini-3.5-flash"
    assert attempt.ocr_text == "Document workflow screenshots"
    assert attempt.vision_raw_output["ui_state"] == "loaded"
    assert "base_url" not in attempt.model_metadata
    assert attempt.model_metadata["base_url_host_hash"]
    assert attempt.model_metadata["prompt_tokens"] == 11
    payload = server.requests[0]
    assert payload["model"] == "gemini-3.5-flash"
    assert payload["messages"][1]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
