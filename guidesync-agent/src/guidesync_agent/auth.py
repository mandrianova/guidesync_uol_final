from __future__ import annotations

import base64
import secrets

from fastapi import Request
from starlette.responses import Response

from guidesync_agent.config import auth_config


def auth_is_configured() -> bool:
    config = auth_config()
    return config.mode == "basic" and bool(config.username and config.password)


def basic_auth_response() -> Response:
    return Response(
        "Authentication required",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="GuideSync"'},
    )


def request_is_authorized(request: Request) -> bool:
    config = auth_config()
    if config.mode in {"", "none", "disabled"}:
        return True
    if config.mode != "basic":
        return False
    if not config.username or not config.password:
        return False

    scheme, _, encoded = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except Exception:  # noqa: BLE001 - invalid user input should simply fail auth
        return False
    username, separator, password = decoded.partition(":")
    if not separator:
        return False
    return secrets.compare_digest(username, config.username) and secrets.compare_digest(
        password,
        config.password,
    )
