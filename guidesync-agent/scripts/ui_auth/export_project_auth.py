from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import termios
import time
from dataclasses import dataclass

AUTH0_PREFIX = "@@auth0spajs@@"
AUTH0_ACCESS_SUFFIX = "::default::openid profile email"
AUTH0_USER_SUFFIX = "::@@user@@"
EXPIRY_WARNING_SECONDS = 5 * 60
ID_TOKEN_PROTOCOL_CLAIMS = {
    "aud",
    "auth_time",
    "azp",
    "exp",
    "iat",
    "iss",
    "jti",
    "nbf",
    "nonce",
    "org_id",
    "sid",
}


@dataclass(frozen=True)
class SavedProjectAuth:
    project_id: str
    project_name: str
    secret: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update Auth0 tokens in saved project UI authorization."
    )
    parser.add_argument(
        "--project",
        default="Ardor",
        help="GuideSync project ID or exact name (default: Ardor).",
    )
    return parser.parse_args()


def read_saved_project_auth(project: str) -> SavedProjectAuth:
    query = """
SELECT json_build_object(
    'project_id', id,
    'project_name', name,
    'secret', task_interface_auth_secret
)::text
FROM guidesync_projects
WHERE id = :'project' OR lower(name) = lower(:'project')
ORDER BY id;
"""
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "guidesync",
            "-d",
            "guidesync",
            "-X",
            "-A",
            "-t",
            "-v",
            f"project={project}",
            "-f",
            "-",
        ],
        input=query,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "Could not read the GuideSync database."
        raise RuntimeError(detail)
    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"GuideSync project not found: {project}")
    if len(rows) > 1:
        raise ValueError(f"More than one GuideSync project matched: {project}")
    row = rows[0]
    if not row["secret"]:
        raise ValueError(
            "The project has no saved UI authorization with reusable Auth0 entries."
        )
    return SavedProjectAuth(
        project_id=row["project_id"],
        project_name=row["project_name"],
        secret=row["secret"],
    )


def normalize_bearer(token: str) -> str:
    value = token.strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    if not value:
        raise ValueError("Bearer token is empty.")
    return value


def read_hidden_line(prompt: str) -> str:
    if not sys.stdin.isatty():
        print(prompt, end="", flush=True)
        return sys.stdin.readline().strip()

    file_descriptor = sys.stdin.fileno()
    original = termios.tcgetattr(file_descriptor)
    hidden = termios.tcgetattr(file_descriptor)
    hidden[3] &= ~(termios.ECHO | termios.ICANON)
    characters = bytearray()
    print(prompt, end="", flush=True)
    try:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, hidden)
        while True:
            character = os.read(file_descriptor, 1)
            if character in {b"\n", b"\r"}:
                break
            if character == b"\x03":
                raise KeyboardInterrupt
            if character in {b"\x7f", b"\x08"}:
                if characters:
                    characters.pop()
                continue
            characters.extend(character)
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, original)
        print()
    return characters.decode().strip()


def decode_jwt(token: str) -> tuple[list[str], dict[str, object], dict[str, object]]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("JWT must contain three segments.")
    try:
        header = json.loads(
            base64.urlsafe_b64decode(parts[0] + "=" * (-len(parts[0]) % 4))
        )
        claims = json.loads(
            base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Could not decode JWT.") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise ValueError("JWT header and claims must be JSON objects.")
    return parts, header, claims


def jwt_expiration(token: str) -> int | None:
    try:
        _, _, claims = decode_jwt(token)
    except ValueError:
        return None
    expiration = claims.get("exp")
    return expiration if isinstance(expiration, int) else None


def validate_expiration(source: str, token: str) -> None:
    expiration = jwt_expiration(token)
    if expiration is None:
        raise ValueError(f"Could not read JWT expiration: {source}")
    remaining = expiration - int(time.time())
    if remaining <= 0:
        raise ValueError(f"JWT is expired: {source}")
    if remaining < EXPIRY_WARNING_SECONDS:
        print(f"Warning: JWT expires in less than 5 minutes: {source}", file=sys.stderr)


def auth0_cache_keys(authorization: dict[str, str]) -> tuple[str, str]:
    access_key = next(
        (
            key
            for key in authorization
            if key.startswith(AUTH0_PREFIX) and key.endswith(AUTH0_ACCESS_SUFFIX)
        ),
        None,
    )
    user_key = next(
        (
            key
            for key in authorization
            if key.startswith(AUTH0_PREFIX) and key.endswith(AUTH0_USER_SUFFIX)
        ),
        None,
    )
    if access_key is None or user_key is None:
        raise ValueError("Saved UI authorization has no reusable Auth0 cache entries.")
    return access_key, user_key


def refreshed_access_entry(raw_entry: str, access_token: str) -> str:
    access_entry = json.loads(raw_entry)
    access_body = access_entry.get("body") if isinstance(access_entry, dict) else None
    if not isinstance(access_body, dict):
        raise ValueError("Saved Auth0 access-token cache entry is invalid.")
    access_expiration = jwt_expiration(access_token)
    if access_expiration is None:
        raise ValueError("Could not read JWT expiration: Auth0 access token")
    access_body["access_token"] = access_token
    access_entry["expiresAt"] = access_expiration - 1
    return json.dumps(access_entry, separators=(",", ":"))


def refreshed_user_entry(raw_entry: str, id_token: str) -> str:
    id_parts, id_header, id_claims = decode_jwt(id_token)
    user_entry = json.loads(raw_entry)
    if not isinstance(user_entry, dict):
        raise ValueError("Saved Auth0 user cache entry is invalid.")
    user_entry["id_token"] = id_token
    user_entry["decodedToken"] = {
        "encoded": {
            "header": id_parts[0],
            "payload": id_parts[1],
            "signature": id_parts[2],
        },
        "header": id_header,
        "claims": {"__raw": id_token, **id_claims},
        "user": {
            key: value
            for key, value in id_claims.items()
            if key not in ID_TOKEN_PROTOCOL_CLAIMS
        },
    }
    return json.dumps(user_entry, separators=(",", ":"))


def refreshed_authorization(
    secret: str,
    auth0_access_token: str,
    auth0_id_token: str,
) -> dict[str, str]:
    raw_authorization = json.loads(secret)
    if not isinstance(raw_authorization, dict):
        raise ValueError("Saved UI authorization must be a JSON object.")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in raw_authorization.items()
    ):
        raise ValueError("Saved UI authorization must map string keys to string values.")
    authorization: dict[str, str] = dict(raw_authorization)
    access_key, user_key = auth0_cache_keys(authorization)

    access_token = normalize_bearer(auth0_access_token)
    id_token = normalize_bearer(auth0_id_token)
    validate_expiration("Auth0 access token", access_token)
    validate_expiration("Auth0 ID token", id_token)
    authorization[access_key] = refreshed_access_entry(
        authorization[access_key], access_token
    )
    authorization[user_key] = refreshed_user_entry(authorization[user_key], id_token)
    authorization.pop("accessToken", None)
    return authorization


def save_project_auth(saved: SavedProjectAuth, authorization: dict[str, str]) -> None:
    serialized = json.dumps(authorization, separators=(",", ":"))
    encoded = base64.b64encode(serialized.encode()).decode()
    query = f"""
UPDATE guidesync_projects
SET task_interface_auth_secret = convert_from(decode('{encoded}', 'base64'), 'UTF8')
WHERE id = :'project'
RETURNING id;
"""
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "guidesync",
            "-d",
            "guidesync",
            "-X",
            "-A",
            "-t",
            "-v",
            f"project={saved.project_id}",
            "-f",
            "-",
        ],
        input=query,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "Could not update the GuideSync database."
        raise RuntimeError(detail)
    if saved.project_id not in completed.stdout.splitlines():
        raise RuntimeError("The GuideSync project authorization was not updated.")


def main() -> int:
    args = parse_args()
    try:
        saved = read_saved_project_auth(args.project)
        access_token = read_hidden_line(
            "Fresh Auth0 access token (body.access_token; hidden): "
        )
        id_token = read_hidden_line(
            "Fresh Auth0 ID token (id_token; hidden): "
        )
        authorization = refreshed_authorization(saved.secret, access_token, id_token)
        save_project_auth(saved, authorization)
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"Local command failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Updated UI authorization for {saved.project_name} ({saved.project_id})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
