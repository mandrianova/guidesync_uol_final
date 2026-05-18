from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


MVP_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = MVP_ROOT.parents[1]
STATIC_ROOT = MVP_ROOT / "ui"
INPUT_ROOT = MVP_ROOT / "inputs" / "projects"
OUTPUT_ROOT = MVP_ROOT / "outputs" / "projects"


def slug(value: str, fallback: str = "task") -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return normalized or fallback


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_project_id(value: str) -> str:
    project_id = slug(value, "project")
    if project_id in {".", ".."}:
        raise ValueError("Invalid project id")
    return project_id


def resolve_inside(base: Path, raw_path: str) -> Path:
    candidate = (base / raw_path).resolve()
    base_resolved = base.resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise ValueError("Path is outside allowed directory")
    return candidate


def parse_lines(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def parse_csv(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        parts = value
    else:
        parts = str(value).replace("\n", ",").split(",")
    return [str(item).strip() for item in parts if str(item).strip()]


def repo_entries(value: str | list[str] | None) -> list[dict[str, str]]:
    entries = []
    for raw_line in parse_lines(value):
        if "|" in raw_line:
            name, path = raw_line.split("|", 1)
            entries.append({"name": name.strip(), "path": path.strip()})
        else:
            entries.append({"path": raw_line})
    return [entry for entry in entries if entry.get("path")]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in payload.items():
        if value in ("", None, [], {}):
            continue
        result[key] = value
    return result


def default_output_dir(project_id: str, task_id: str) -> str:
    return f"outputs/projects/{project_id}/tasks/{task_id}"


def artifact_path(path: Path) -> str:
    return str(path.resolve().relative_to(MVP_ROOT.resolve()))


def list_files(root: Path, suffixes: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    files: list[dict[str, Any]] = []
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        if suffixes and file_path.suffix.lower() not in suffixes:
            continue
        files.append(
            {
                "path": artifact_path(file_path),
                "name": file_path.name,
                "size": file_path.stat().st_size,
                "modified": datetime.fromtimestamp(file_path.stat().st_mtime, timezone.utc).isoformat(),
            }
        )
    return files


def discover_projects() -> list[dict[str, Any]]:
    INPUT_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    projects: list[dict[str, Any]] = []
    for project_dir in sorted(path for path in INPUT_ROOT.iterdir() if path.is_dir()):
        project_id = project_dir.name
        project_json = project_dir / "project.json"
        raw_project = load_json(project_json) if project_json.exists() else {}
        project = raw_project.get("project", raw_project) if isinstance(raw_project, dict) else {}
        tasks = []
        for task_path in sorted(project_dir.glob("*task*.json")):
            tasks.append({"name": task_path.name, "path": artifact_path(task_path)})
        output_dir = OUTPUT_ROOT / project_id
        output_files = list_files(output_dir, (".html", ".md", ".json", ".png", ".jpg", ".jpeg", ".webp"))
        projects.append(
            {
                "id": project_id,
                "name": project.get("name") or project_id,
                "root": project.get("root", ""),
                "languages": project.get("languages", []),
                "tasks": tasks,
                "outputs": output_files[-30:],
            }
        )
    return projects


def build_init_task(form: dict[str, Any]) -> tuple[str, Path, dict[str, Any]]:
    project_id = safe_project_id(form.get("project_id", "project"))
    project_dir = INPUT_ROOT / project_id
    languages = parse_csv(form.get("languages")) or ["en"]
    ui_repositories = repo_entries(form.get("ui_repositories"))
    ui: dict[str, Any] = compact_dict(
        {
            "url": str(form.get("ui_url", "")).strip(),
            "repositories": ui_repositories,
            "expected_text": parse_lines(form.get("expected_text")),
            "notes": str(form.get("ui_notes", "")).strip(),
        }
    )
    task = {
        "$schema": "../../project-init-task.schema.json",
        "task_id": f"{project_id}-project-init",
        "created_at": now_iso(),
        "task": compact_dict(
            {
                "type": "project_init",
                "id": "project-init",
                "description": str(form.get("task_description", "")).strip(),
            }
        ),
        "project": compact_dict(
            {
                "id": project_id,
                "name": str(form.get("project_name", "")).strip() or project_id,
                "description": str(form.get("project_description", "")).strip(),
                "root": str(form.get("project_root", "")).strip(),
                "env_file": str(form.get("env_file", "")).strip() or ".env",
                "languages": languages,
            }
        ),
        "ui": ui,
        "output": {"project_dir": f"inputs/projects/{project_id}"},
    }
    task_path = project_dir / "init-project-task.json"
    write_json(task_path, task)
    return project_id, task_path, task


def build_release_task(form: dict[str, Any]) -> tuple[str, Path, dict[str, Any]]:
    project_id = safe_project_id(form.get("project_id", "project"))
    project_dir = INPUT_ROOT / project_id
    task_id = slug(str(form.get("task_id", "")).strip() or "recent-user-facing-changes", "release")
    languages = parse_csv(form.get("languages"))
    auth_mode = str(form.get("auth_mode", "none")).strip() or "none"
    ui_launch_mode = str(form.get("launch_mode", "none")).strip() or "none"
    output_dir = str(form.get("output_dir", "")).strip() or default_output_dir(project_id, task_id)

    project: dict[str, Any] = compact_dict(
        {
            "id": project_id,
            "name": str(form.get("project_name", "")).strip() or project_id,
            "description": str(form.get("project_description", "")).strip(),
            "root": str(form.get("project_root", "")).strip(),
            "env_file": str(form.get("env_file", "")).strip() or ".env",
            "languages": languages,
        }
    )
    project_config = project_dir / "project.json"
    if project_config.exists():
        raw_saved = load_json(project_config)
        saved = raw_saved.get("project", raw_saved) if isinstance(raw_saved, dict) else {}
        for key in ("name", "description", "root", "env_file", "languages", "branding", "copy"):
            if key not in project and saved.get(key):
                project[key] = saved[key]

    ui: dict[str, Any] = compact_dict(
        {
            "url": str(form.get("ui_url", "")).strip(),
            "max_screenshots": int(form.get("max_screenshots") or 5),
            "wait_after_ms": int(form.get("wait_after_ms") or 1500),
            "expected_text": parse_lines(form.get("expected_text")),
            "headed": bool(form.get("headed")),
            "manual_auth": bool(form.get("manual_auth")),
            "launch": compact_dict(
                {
                    "mode": ui_launch_mode,
                    "compose_file": str(form.get("compose_file", "")).strip(),
                    "project_name": str(form.get("compose_project_name", "")).strip(),
                    "service": str(form.get("compose_service", "")).strip(),
                    "image": str(form.get("docker_image", "")).strip(),
                    "ports": parse_csv(form.get("docker_ports")),
                    "env_file": str(form.get("docker_env_file", "")).strip(),
                    "wait_url": str(form.get("wait_url", "")).strip(),
                    "timeout_seconds": int(form.get("timeout_seconds") or 120),
                    "down_after": bool(form.get("down_after")),
                    "remove": bool(form.get("remove")),
                }
            ),
        }
    )
    auth = compact_dict(
        {
            "mode": auth_mode,
            "env_file": str(form.get("env_file", "")).strip() or ".env",
            "token_env": str(form.get("token_env", "")).strip(),
            "role": str(form.get("auth_role", "")).strip(),
            "notes": str(form.get("auth_notes", "")).strip(),
        }
    )
    task = {
        "$schema": "../../release-task.schema.json",
        "task_id": f"{project_id}-{task_id}",
        "created_at": now_iso(),
        "project": project,
        "task": compact_dict(
            {
                "id": task_id,
                "description": str(form.get("task_description", "")).strip()
                or "Collect recent repository changes and produce user-facing release notes with UI evidence.",
                "audience": str(form.get("audience", "")).strip() or "ordinary product users",
                "example_context": str(form.get("example_context", "")).strip(),
            }
        ),
        "repositories": repo_entries(form.get("repositories")),
        "period": compact_dict(
            {
                "since": str(form.get("since", "")).strip() or "2 weeks ago",
                "until": str(form.get("until", "")).strip(),
            }
        ),
        "ref": str(form.get("ref", "")).strip() or "HEAD",
        "max_features": int(form.get("max_features") or 8),
        "auth": auth,
        "ui": ui,
        "output": compact_dict({"dir": output_dir, "title": str(form.get("output_title", "")).strip()}),
    }
    task_path = project_dir / "release-task.json"
    write_json(task_path, task)
    return project_id, task_path, task


def collect_artifacts(task: dict[str, Any]) -> list[dict[str, Any]]:
    project_id = safe_project_id(task.get("project", {}).get("id", "project"))
    output = task.get("output", {})
    raw_dir = output.get("dir")
    if raw_dir:
        output_dir = (MVP_ROOT / raw_dir).resolve() if not os.path.isabs(raw_dir) else Path(raw_dir).resolve()
    elif task.get("task", {}).get("type") == "project_init":
        output_dir = OUTPUT_ROOT / project_id
    else:
        task_id = task.get("task", {}).get("id") or "recent-user-facing-changes"
        output_dir = OUTPUT_ROOT / project_id / "tasks" / task_id
    if MVP_ROOT.resolve() not in output_dir.parents and output_dir != MVP_ROOT.resolve():
        return []
    return list_files(output_dir, (".html", ".md", ".json", ".png", ".jpg", ".jpeg", ".webp"))


class GuideSyncHandler(BaseHTTPRequestHandler):
    server_version = "GuideSyncUI/0.1"

    def do_GET(self) -> None:  # noqa: N802
        try:
            self.route_get()
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        try:
            self.route_post()
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[guidesync-ui] {self.address_string()} - {format % args}")

    def route_get(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/projects":
            self.send_json({"projects": discover_projects()})
            return
        if parsed.path == "/api/artifact":
            params = parse_qs(parsed.query)
            raw_path = params.get("path", [""])[0]
            self.send_file(resolve_inside(MVP_ROOT, raw_path))
            return
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_file(STATIC_ROOT / "index.html")
            return
        static_path = parsed.path.lstrip("/")
        self.send_file(resolve_inside(STATIC_ROOT, static_path))

    def route_post(self) -> None:
        parsed = urlparse(self.path)
        body = self.read_json()
        if parsed.path == "/api/tasks/init":
            project_id, task_path, task = build_init_task(body)
            self.send_json({"project_id": project_id, "task_path": artifact_path(task_path), "task": task})
            return
        if parsed.path == "/api/tasks/release":
            project_id, task_path, task = build_release_task(body)
            self.send_json({"project_id": project_id, "task_path": artifact_path(task_path), "task": task})
            return
        if parsed.path == "/api/run":
            raw_task_path = str(body.get("task_path", "")).strip()
            task_path = resolve_inside(MVP_ROOT, raw_task_path)
            if not task_path.exists():
                raise ValueError("Task file does not exist")
            task = load_json(task_path)
            process = subprocess.run(
                [str(MVP_ROOT / "scripts" / "run_task.sh"), str(task_path)],
                cwd=str(WORKSPACE_ROOT),
                text=True,
                capture_output=True,
                timeout=int(body.get("timeout_seconds") or 1200),
                check=False,
            )
            self.send_json(
                {
                    "returncode": process.returncode,
                    "stdout": process.stdout,
                    "stderr": process.stderr,
                    "artifacts": collect_artifacts(task),
                }
            )
            return
        raise ValueError(f"Unsupported endpoint: {parsed.path}")

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".md":
            content_type = "text/markdown; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local GuideSync task UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), GuideSyncHandler)
    print(f"GuideSync UI: http://{args.host}:{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
