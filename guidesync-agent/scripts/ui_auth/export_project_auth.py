from __future__ import annotations

import argparse
import base64
import getpass
import json
import subprocess
import sys
import time
from dataclasses import dataclass

AUTH0_PREFIX = "@@auth0spajs@@"
EXPIRY_WARNING_SECONDS = 5 * 60


@dataclass(frozen=True)
class SavedProjectAuth:
    project_id: str
    project_name: str
    secret: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replace accessToken in saved project UI authorization JSON."
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


def jwt_expiration(token: str) -> int | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
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


def refreshed_authorization(secret: str, bearer: str) -> dict[str, str]:
    authorization = json.loads(secret)
    if not isinstance(authorization, dict):
        raise ValueError("Saved UI authorization must be a JSON object.")
    auth0_keys = [key for key in authorization if key.startswith(AUTH0_PREFIX)]
    if not auth0_keys:
        raise ValueError("Saved UI authorization has no reusable Auth0 cache entries.")

    access_token = normalize_bearer(bearer)
    validate_expiration("accessToken", access_token)
    authorization["accessToken"] = access_token

    for key in auth0_keys:
        cache_entry = json.loads(authorization[key])
        cached_token = cache_entry.get("body", {}).get("access_token") or cache_entry.get(
            "id_token"
        )
        if cached_token:
            validate_expiration(key, cached_token)
    return authorization


def copy_to_clipboard(value: str) -> None:
    subprocess.run(["pbcopy"], input=value, text=True, check=True)


def main() -> int:
    args = parse_args()
    try:
        saved = read_saved_project_auth(args.project)
        current = json.loads(saved.secret).get("accessToken", "")
        entered = getpass.getpass(
            "Fresh Bearer token (hidden; leave empty to keep the saved accessToken): "
        )
        authorization = refreshed_authorization(saved.secret, entered or current)
        output = json.dumps(authorization, separators=(",", ":"))
        copy_to_clipboard(output)
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Local command failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Copied UI authorization JSON for {saved.project_name} "
        f"({saved.project_id}) with {len(authorization)} keys."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
