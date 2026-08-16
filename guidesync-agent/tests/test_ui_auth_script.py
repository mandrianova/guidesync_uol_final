from __future__ import annotations

import base64
import json
import time

import pytest

from scripts.ui_auth.export_project_auth import refreshed_authorization

AUTH0_ACCESS_KEY = (
    "@@auth0spajs@@::client-id::default::openid profile email"
)
AUTH0_USER_KEY = "@@auth0spajs@@::client-id::@@user@@"


def _jwt(claims: dict[str, object]) -> str:
    def encode(value: dict[str, object]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{encode({'alg': 'RS256', 'typ': 'JWT'})}.{encode(claims)}.signature"


def _saved_authorization() -> str:
    return json.dumps(
        {
            "accessToken": "obsolete",
            AUTH0_ACCESS_KEY: json.dumps(
                {
                    "body": {"access_token": "old", "scope": "openid profile email"},
                    "expiresAt": 1,
                }
            ),
            AUTH0_USER_KEY: json.dumps(
                {"id_token": "old", "decodedToken": {"user": {"name": "Old"}}}
            ),
        }
    )


def test_refreshes_both_auth0_entries_and_removes_legacy_access_token() -> None:
    now = int(time.time())
    access_token = _jwt({"exp": now + 3600, "scope": "openid profile email"})
    id_token = _jwt(
        {
            "exp": now + 1800,
            "iat": now,
            "iss": "https://auth.example/",
            "sub": "auth0|user",
            "email": "person@example.com",
        }
    )

    authorization = refreshed_authorization(
        _saved_authorization(), access_token, id_token
    )

    assert "accessToken" not in authorization
    access_entry = json.loads(authorization[AUTH0_ACCESS_KEY])
    assert access_entry["body"]["access_token"] == access_token
    assert access_entry["expiresAt"] == now + 3599

    user_entry = json.loads(authorization[AUTH0_USER_KEY])
    assert user_entry["id_token"] == id_token
    assert user_entry["decodedToken"]["claims"]["__raw"] == id_token
    assert user_entry["decodedToken"]["user"] == {
        "sub": "auth0|user",
        "email": "person@example.com",
    }


def test_rejects_an_expired_auth0_token() -> None:
    expired = _jwt({"exp": int(time.time()) - 1})
    valid = _jwt({"exp": int(time.time()) + 3600})

    with pytest.raises(ValueError, match="JWT is expired: Auth0 access token"):
        refreshed_authorization(_saved_authorization(), expired, valid)


def test_rejects_missing_auth0_cache_entries() -> None:
    valid = _jwt({"exp": int(time.time()) + 3600})

    with pytest.raises(ValueError, match="no reusable Auth0 cache entries"):
        refreshed_authorization("{}", valid, valid)
