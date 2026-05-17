from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from guidesync_mvp.capture import run_capture


USER_FACING_FILE_HINTS = (
    "src/routes/",
    "src/pages/",
    "src/app/",
    "src/features/",
    "src/components/",
    "app/",
    "pages/",
    "components/",
    "features/",
)

USER_FACING_MESSAGE_HINTS = (
    "feat",
    "feature",
    "add",
    "added",
    "implement",
    "ui",
    "ux",
    "screen",
    "page",
    "form",
    "button",
    "settings",
    "dashboard",
    "workflow",
    "guide",
)

INTERNAL_FILE_HINTS = (
    ".cursor/",
    "api/@tanstack/",
    "api/sdk.gen.",
    "api/types.gen.",
    "api/zod.gen.",
    "api/model-capabilities.gen.",
    "test/",
    "tests/",
    "__tests__/",
    ".spec.",
    ".test.",
    "lock",
    "package-lock",
    "uv.lock",
    "docs/",
    "alembic/",
    "migrations/",
    "bundled/",
)

INTERNAL_ROUTE_HINTS = (
    "/",
    "/__root",
    "/components/",
    "/dev/",
    "/debug/",
    "/storybook",
)

TECHNICAL_SUBJECT_HINTS = (
    "align",
    "foundation",
    "runtime",
    "storage",
    "untrack",
    "polish",
    "tighten",
    "contract",
    "tests",
    "overlay",
    "overlays",
    "toggle",
    "toggles",
)

USER_TITLE_PATTERNS = (
    (("domain",), "Пользовательские домены"),
    (("resource", "mention"), "Упоминания файлов и ресурсов в чате"),
    (("slash", "command"), "Slash-команды в чате"),
    (("workspace", "permission"), "Управление доступом к рабочей области"),
    (("permission", "control"), "Управление доступом"),
    (("skill",), "Навыки агента"),
)

AREA_LABELS = {
    "account menu": "меню аккаунта",
    "billing": "оплата и тариф",
    "chat": "чат",
    "common layout": "основной интерфейс",
    "domains": "домены",
    "homepage": "главная страница",
    "markdown": "сообщения и публикации",
    "settings": "настройки",
    "solution": "проект",
    "ui": "интерфейс",
}

LOW_SIGNAL_AREAS = {
    "common layout",
    "markdown",
    "modals",
    "ui",
}

AREA_PRIORITY = (
    "domains",
    "account menu",
    "settings",
    "billing",
    "chat",
    "homepage",
    "solution",
)


@dataclass(frozen=True)
class CommitChange:
    repo_name: str
    repo_path: Path
    sha: str
    date: str
    subject: str
    body: str
    files: list[str]


def run_git(repo: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def ensure_repo(path: Path) -> Path:
    repo = path.expanduser().resolve()
    if not (repo / ".git").exists():
        raise SystemExit(f"Not a git repository: {repo}")
    return repo


def collect_commits(repo: Path, since: str, until: str | None, ref: str) -> list[CommitChange]:
    log_args = ["log", ref, f"--since={since}", "--date=short", "--pretty=format:%H%x1f%ad%x1f%s%x1f%b%x1e"]
    if until:
        log_args.insert(3, f"--until={until}")
    raw = run_git(repo, log_args)
    changes: list[CommitChange] = []
    for record in raw.split("\x1e"):
        if not record.strip():
            continue
        parts = record.split("\x1f", maxsplit=3)
        if len(parts) < 3:
            continue
        if len(parts) == 3:
            parts.append("")
        sha, date, subject, body = [part.strip() for part in parts]
        files_raw = run_git(repo, ["show", "--name-only", "--pretty=format:", sha])
        files = [line.strip() for line in files_raw.splitlines() if line.strip()]
        changes.append(
            CommitChange(
                repo_name=repo.name,
                repo_path=repo,
                sha=sha,
                date=date,
                subject=subject.strip(),
                body=body.strip(),
                files=files,
            )
        )
    return changes


def is_internal_file(path: str) -> bool:
    lower = path.lower()
    return any(hint in lower for hint in INTERNAL_FILE_HINTS)


def user_facing_score(change: CommitChange) -> int:
    text = f"{change.subject}\n{change.body}".lower()
    score = sum(2 for hint in USER_FACING_MESSAGE_HINTS if hint in text)
    if any(hint in text for hint in TECHNICAL_SUBJECT_HINTS):
        score -= 8
    if any(hint in text for hint in ("domain", "permission", "slash command", "resource mention")):
        score += 8
    for file_path in change.files:
        lower = file_path.lower()
        if is_internal_file(lower):
            score -= 3
            continue
        if any(hint in lower for hint in USER_FACING_FILE_HINTS):
            score += 3
        if re.search(r"\.(tsx|jsx|vue|svelte|html|mdx|md)$", lower):
            score += 1
    return score


def has_frontend_surface(change: CommitChange) -> bool:
    for file_path in change.files:
        lower = file_path.lower()
        if is_internal_file(lower):
            continue
        if lower.startswith(("src/routes/", "src/pages/", "src/app/", "app/", "pages/")):
            return True
        if lower.startswith(("src/features/", "src/components/", "features/", "components/")) and re.search(
            r"\.(tsx|jsx|vue|svelte|html|mdx)$", lower
        ):
            return True
    return False


def is_publishable_change(change: CommitChange) -> bool:
    if not has_frontend_surface(change):
        return False
    title = human_title(change.subject).lower()
    if any(hint in title for hint in TECHNICAL_SUBJECT_HINTS) and not route_hints(change.files):
        return False
    if any(hint in title for hint in ("overlay", "panel toggle", "polish")):
        return False
    return bool(route_hints(change.files) or feature_hints(change.files))


def human_title(subject: str) -> str:
    title = re.sub(r"^(feat|fix|chore|docs|refactor|style|test|perf)(\([^)]+\))?:\s*", "", subject, flags=re.I)
    title = title.strip(" .")
    return title[:1].upper() + title[1:] if title else subject


def user_facing_title(raw_title: str, features: list[str], routes: list[str]) -> str:
    text = " ".join([raw_title, *features, *routes]).lower()
    for needles, title in USER_TITLE_PATTERNS:
        if all(needle in text for needle in needles):
            return title
    cleaned = re.sub(r"\s*\(#\d+\)\s*$", "", raw_title).strip()
    cleaned = re.sub(r"^(add|implement|support|create|update)\s+", "", cleaned, flags=re.I).strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else raw_title


def route_hints(files: list[str]) -> list[str]:
    hints: list[str] = []
    for file_path in files:
        normalized = file_path.replace("\\", "/")
        if "domains" in normalized and "/routes/" in normalized:
            hints.append("/agent/:sessionId/domains")
            continue
        route_match = re.search(r"(?:src/)?routes/(.+?)\.(tsx|jsx|ts|js)$", normalized)
        page_match = re.search(r"(?:src/)?pages/(.+?)\.(tsx|jsx|ts|js)$", normalized)
        app_match = re.search(r"app/(.+?)/(?:page|layout)\.(tsx|jsx|ts|js)$", normalized)
        raw_route = None
        if route_match:
            raw_route = route_match.group(1)
        elif page_match:
            raw_route = page_match.group(1)
        elif app_match:
            raw_route = app_match.group(1)
        if not raw_route:
            continue
        route = "/" + raw_route
        route = route.replace("index", "").replace("$", ":")
        route = "/".join(part for part in route.split("/") if part and not part.startswith("_"))
        route = "/" + route if route else "/"
        route = re.sub(r"/+", "/", route)
        route = route.rstrip("/") or "/"
        if route in INTERNAL_ROUTE_HINTS or any(route.startswith(hint) for hint in INTERNAL_ROUTE_HINTS):
            continue
        if route not in hints:
            hints.append(route)
    return hints[:5]


def feature_hints(files: list[str]) -> list[str]:
    names: list[str] = []
    for file_path in files:
        normalized = file_path.replace("\\", "/")
        match = re.search(r"(?:src/)?features/([^/]+)", normalized)
        if not match:
            match = re.search(r"(?:src/)?components/([^/]+)", normalized)
        if match:
            name = match.group(1).replace("-", " ").replace("_", " ").strip()
            if "." in name:
                continue
            if name and name not in LOW_SIGNAL_AREAS and name not in names:
                names.append(name)
    names.sort(key=lambda name: AREA_PRIORITY.index(name) if name in AREA_PRIORITY else len(AREA_PRIORITY))
    return names[:5]


def display_area(area: str) -> str:
    return AREA_LABELS.get(area, area.replace("-", " ").replace("_", " "))


def display_route(route: str) -> str:
    if route == "/":
        return "главная страница"
    cleaned = route.strip("/")
    if not cleaned:
        return "главная страница"
    return " / ".join(part.replace(":", "").replace("-", " ") for part in cleaned.split("/"))


def display_audience(audience: str) -> str:
    lowered = audience.lower().strip()
    if lowered in {"ordinary users", "regular users", "ordinary ardor users"}:
        return "обычный пользователь"
    return audience


def usage_steps(title: str, routes: list[str], features: list[str]) -> list[str]:
    steps = []
    if routes:
        steps.append(f"Откройте продукт и перейдите в раздел “{display_route(routes[0])}”.")
    elif features:
        steps.append(f"Откройте раздел продукта, связанный с “{display_area(features[0])}”.")
    else:
        steps.append("Откройте продукт и найдите новый или изменённый раздел в основном меню.")
    steps.append(f"Найдите на экране элементы, связанные с “{title}”.")
    steps.append("Следуйте подсказкам интерфейса и заполните только необходимые поля.")
    steps.append("Проверьте результат на странице перед тем, как считать настройку завершённой.")
    return steps


def usage_examples(title: str, routes: list[str], features: list[str], audience: str, example_context: str) -> list[dict[str, str]]:
    location = display_route(routes[0]) if routes else (display_area(features[0]) if features else "нужный раздел продукта")
    cleaned_context = example_context.strip().rstrip(".")
    context_prefix = f"{cleaned_context}. " if cleaned_context and not cleaned_context.lower().startswith("use examples") else ""
    readable_audience = display_audience(audience)
    return [
        {
            "title": "Найти функцию в интерфейсе",
            "scenario": f"{context_prefix}Пользователь открывает “{location}” и ищет в интерфейсе “{title}” по видимым заголовкам, кнопкам или подсказкам.",
            "expected_result": "Пользователь видит, где находится функция, без чтения технических подробностей.",
        },
        {
            "title": "Применить в рабочей задаче",
            "scenario": f"{readable_audience.capitalize()} выполняет обычное действие в этом разделе: выбирает доступную опцию, вводит безопасные тестовые данные или открывает новый элемент, связанный с “{title}”.",
            "expected_result": "Пользователь понимает, что изменилось в продукте и как проверить результат в UI.",
        },
    ]


def build_feature(change: CommitChange, *, audience: str, example_context: str) -> dict[str, Any]:
    routes = route_hints(change.files)
    features = feature_hints(change.files)
    evidence_files = [file_path for file_path in change.files if not is_internal_file(file_path.lower())]
    technical_title = human_title(change.subject)
    title = user_facing_title(technical_title, features, routes)
    return {
        "title": title,
        "technical_title": technical_title,
        "summary": summarise_change(title, routes, features),
        "repo": change.repo_name,
        "commit": change.sha[:8],
        "date": change.date,
        "routes": routes,
        "areas": features,
        "steps": usage_steps(title, routes, features),
        "examples": usage_examples(title, routes, features, audience, example_context),
        "files": evidence_files[:12],
        "score": user_facing_score(change),
    }


def summarise_change(title: str, routes: list[str], features: list[str]) -> str:
    if routes:
        return f"В интерфейсе появился или изменился раздел “{title}”. Начните проверку с экрана “{display_route(routes[0])}”."
    if features:
        return f"В интерфейсе появилась или изменилась возможность “{title}” в области “{display_area(features[0])}”."
    return f"В продукте появилось изменение “{title}”, но его место в UI нужно подтвердить вручную."


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_input(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def resolve_path(raw_path: str | Path | None, *, input_path: Path | None, project_root: Path | None = None) -> Path | None:
    if raw_path is None or raw_path == "":
        return None
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    if project_root:
        return project_root / path
    if input_path:
        return input_path.parent / path
    return path


def resolve_env_file(raw_path: str | Path | None, *, input_path: Path | None, project_root: Path | None = None) -> Path | None:
    if raw_path is None or raw_path == "":
        return None
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    candidates: list[Path] = []
    if input_path:
        candidates.append(input_path.parent / path)
    if project_root:
        candidates.append(project_root / path)
    candidates.append(path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_env_file(path: Path | None) -> None:
    if not path or not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def wait_for_url(url: str, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310 - local/dev readiness probe
                if response.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001 - keep last readiness error
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for UI at {url}: {last_error}")


def launch_ui(ui: dict[str, Any]) -> tuple[dict[str, Any], Any | None]:
    launch = ui.get("launch") or {}
    mode = launch.get("mode", "none")
    if mode == "none":
        return {"status": "skipped", "mode": "none"}, None

    wait_url = launch.get("wait_url") or ui.get("url")
    timeout_seconds = int(launch.get("timeout_seconds", 90))

    if mode == "docker_compose":
        compose_file = launch.get("compose_file")
        if not compose_file:
            raise ValueError("ui.launch.compose_file is required for docker_compose mode")
        command = ["docker", "compose", "-f", str(compose_file)]
        if launch.get("project_name"):
            command.extend(["-p", str(launch["project_name"])])
        command.extend(["up", "-d"])
        if launch.get("service"):
            command.append(str(launch["service"]))
        subprocess.run(command, check=True)
        if wait_url:
            wait_for_url(str(wait_url), timeout_seconds)
        return {
            "status": "started",
            "mode": mode,
            "compose_file": str(compose_file),
            "service": launch.get("service"),
            "wait_url": wait_url,
        }, None

    if mode == "docker_run":
        image = launch.get("image")
        if not image:
            raise ValueError("ui.launch.image is required for docker_run mode")
        command = ["docker", "run", "-d"]
        if launch.get("name"):
            command.extend(["--name", str(launch["name"])])
        if launch.get("remove", True):
            command.append("--rm")
        if launch.get("env_file"):
            command.extend(["--env-file", str(launch["env_file"])])
        for port in launch.get("ports", []):
            command.extend(["-p", str(port)])
        for volume in launch.get("volumes", []):
            command.extend(["-v", str(volume)])
        for key, value in (launch.get("env") or {}).items():
            command.extend(["-e", f"{key}={value}"])
        command.append(str(image))
        command.extend(str(part) for part in launch.get("args", []))
        container_id = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
        if wait_url:
            wait_for_url(str(wait_url), timeout_seconds)
        return {
            "status": "started",
            "mode": mode,
            "image": image,
            "container_id": container_id[:12],
            "wait_url": wait_url,
        }, container_id

    if mode == "command":
        command = launch.get("command")
        if not isinstance(command, list) or not command:
            raise ValueError("ui.launch.command must be a non-empty array for command mode")
        process = subprocess.Popen([str(part) for part in command])
        if wait_url:
            wait_for_url(str(wait_url), timeout_seconds)
        return {"status": "started", "mode": mode, "pid": process.pid, "wait_url": wait_url}, process

    raise ValueError(f"Unsupported ui.launch.mode: {mode}")


def cleanup_ui(ui: dict[str, Any], handle: Any | None) -> None:
    launch = ui.get("launch") or {}
    if not launch.get("down_after", False):
        return
    mode = launch.get("mode", "none")
    if mode == "docker_compose":
        compose_file = launch.get("compose_file")
        if not compose_file:
            return
        command = ["docker", "compose", "-f", str(compose_file)]
        if launch.get("project_name"):
            command.extend(["-p", str(launch["project_name"])])
        command.append("down")
        subprocess.run(command, check=False)
    elif mode == "docker_run" and handle:
        subprocess.run(["docker", "stop", str(handle)], check=False)
    elif mode == "command" and handle:
        handle.terminate()


def resolve_repos(raw_repos: list[Any]) -> list[Path]:
    repos: list[Path] = []
    for entry in raw_repos:
        if isinstance(entry, str):
            repos.append(Path(entry))
        elif isinstance(entry, dict) and entry.get("path"):
            repos.append(Path(entry["path"]))
        else:
            raise SystemExit(f"Invalid repository entry: {entry!r}")
    return repos


def project_id_from_config(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    raw = project.get("id") or project.get("name") or "default-project"
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", str(raw).strip().lower()).strip("-") or "default-project"


def task_id_from_config(config: dict[str, Any]) -> str:
    task = config.get("task") or {}
    raw = task.get("id") or config.get("task_id") or datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S")
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", str(raw).strip().lower()).strip("-") or "run"


def default_output_dir(config: dict[str, Any]) -> Path:
    return Path("outputs") / "projects" / project_id_from_config(config) / "tasks" / task_id_from_config(config)


def css() -> str:
    return """
    :root {
      --bg: #f7f7f4;
      --ink: #1f2528;
      --muted: #647076;
      --line: #d7dddf;
      --panel: #ffffff;
      --accent: #256d85;
      --accent-2: #b44b2a;
      --good: #23704d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .shell { max-width: 1120px; margin: 0 auto; padding: 34px 22px 72px; }
    header { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 22px; align-items: end; border-bottom: 1px solid var(--line); padding-bottom: 28px; }
    h1 { margin: 0; font-size: 46px; line-height: 1.02; letter-spacing: 0; }
    .subtitle { margin: 14px 0 0; color: var(--muted); max-width: 760px; line-height: 1.55; font-size: 16px; }
    .meta { border: 1px solid var(--line); background: var(--panel); padding: 14px 16px; min-width: 260px; }
    .meta div { display: flex; justify-content: space-between; gap: 16px; padding: 5px 0; color: var(--muted); font-size: 13px; }
    .meta strong { color: var(--ink); font-weight: 700; }
    .summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 24px 0; }
    .stat { background: var(--panel); border: 1px solid var(--line); padding: 16px; }
    .stat strong { display: block; font-size: 28px; }
    .stat span { color: var(--muted); font-size: 13px; }
    .feature { background: var(--panel); border: 1px solid var(--line); margin-top: 18px; }
    .feature-head { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 14px; padding: 20px; border-bottom: 1px solid var(--line); }
    h2 { margin: 0; font-size: 24px; letter-spacing: 0; }
    .badge { align-self: start; color: #fff; background: var(--accent); padding: 6px 10px; font-size: 12px; font-weight: 700; }
    .feature-body { display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 20px; padding: 20px; }
    .feature p { color: var(--muted); line-height: 1.58; margin: 8px 0 0; }
    .examples { border-top: 1px solid var(--line); padding: 18px 20px 20px; }
    .example-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 10px; }
    .example { border: 1px solid var(--line); background: #fbfcfc; padding: 14px; }
    .example strong { display: block; margin-bottom: 6px; }
    .example span { display: block; color: var(--muted); line-height: 1.45; font-size: 13px; }
    .shot { border-top: 1px solid var(--line); background: #f9faf9; padding: 0 20px 20px; }
    .shot img { display: block; width: 100%; max-height: 520px; object-fit: contain; border: 1px solid var(--line); background: #fff; }
    .shot p { color: var(--muted); font-size: 13px; margin: 10px 0; }
    ol { margin: 12px 0 0; padding-left: 22px; }
    li { margin: 8px 0; color: var(--ink); line-height: 1.5; }
    code { background: #edf1f2; border: 1px solid var(--line); padding: 1px 5px; }
    .side { border-left: 3px solid var(--accent-2); padding-left: 14px; color: var(--muted); font-size: 13px; }
    .side h3 { margin: 0 0 8px; color: var(--ink); font-size: 13px; text-transform: uppercase; letter-spacing: .06em; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 14px; }
    .chip { border: 1px solid var(--line); background: #fbfcfc; padding: 5px 8px; color: var(--muted); font-size: 12px; }
    footer { margin-top: 28px; padding-top: 18px; border-top: 1px solid var(--line); color: var(--muted); font-size: 13px; line-height: 1.5; }
    @media (max-width: 820px) {
      header, .feature-body, .summary, .example-grid { grid-template-columns: 1fr; }
      h1 { font-size: 34px; }
    }
    """


def render_html(payload: dict[str, Any]) -> str:
    features = [feature for feature in payload["features"] if is_user_visible_feature(feature)]
    feature_cards = "\n".join(render_feature(feature, index + 1) for index, feature in enumerate(features))
    return f"""<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(payload["title"])}</title>
    <style>{css()}</style>
  </head>
  <body>
    <main class="shell">
      <header>
        <div>
          <h1>{html.escape(payload["title"])}</h1>
          <p class="subtitle">Краткий пользовательский гид по новым возможностям: где они находятся в интерфейсе, что с ними можно сделать и как быстро проверить результат.</p>
        </div>
        <aside class="meta">
          <div><span>Период</span><strong>{html.escape(payload["period"])}</strong></div>
          <div><span>Функции</span><strong>{len(features)}</strong></div>
          <div><span>Собрано</span><strong>{html.escape(payload["generated_at"][:10])}</strong></div>
        </aside>
      </header>
      <section class="summary">
        <div class="stat"><strong>{len(features)}</strong><span>новых или изменённых возможностей</span></div>
        <div class="stat"><strong>{count_captured_features(features)}</strong><span>проверено в интерфейсе</span></div>
        <div class="stat"><strong>{count_uncertain_features(payload)}</strong><span>нужно уточнить вручную</span></div>
      </section>
      {feature_cards or render_empty_state()}
      <footer>
        Это черновик пользовательского гайда. Перед публикацией проверьте формулировки, права доступа и соответствие фактическому UI.
      </footer>
    </main>
  </body>
</html>
"""


def is_user_visible_feature(feature: dict[str, Any]) -> bool:
    capture = feature.get("capture") or {}
    return bool(feature.get("routes") or feature.get("areas") or capture.get("status") == "ok")


def count_captured_features(features: list[dict[str, Any]]) -> int:
    return sum(1 for feature in features if (feature.get("capture") or {}).get("status") == "ok")


def count_uncertain_features(payload: dict[str, Any]) -> int:
    return max(0, len(payload.get("features", [])) - len([f for f in payload.get("features", []) if is_user_visible_feature(f)]))


def render_feature(feature: dict[str, Any], index: int) -> str:
    routes = "".join(f'<span class="chip">{html.escape(display_route(route))}</span>' for route in feature["routes"])
    areas = "".join(f'<span class="chip">{html.escape(display_area(area))}</span>' for area in feature["areas"])
    location_blocks = ""
    if routes:
        location_blocks += f"<h3>Где искать</h3><div class=\"chips\">{routes}</div>"
    if areas:
        location_blocks += f"<h3>Связанные разделы</h3><div class=\"chips\">{areas}</div>"
    steps = "".join(f"<li>{html.escape(step)}</li>" for step in feature["steps"])
    examples = "".join(render_example(example) for example in feature.get("examples", []))
    screenshot_html = ""
    capture = feature.get("capture") or {}
    if capture.get("screenshot"):
        screenshot_html = f"""
        <div class="shot">
          <p>Скриншот из автоматической проверки UI: <code>{html.escape(capture.get("route", ""))}</code></p>
          <img src="{html.escape(capture["screenshot"])}" alt="{html.escape(feature["title"])}" />
        </div>
"""
    elif capture.get("status") == "failed":
        screenshot_html = f"""
        <div class="shot">
          <p>UI-проверка для этой функции не прошла: {html.escape(capture.get("error", "unknown error"))}</p>
        </div>
"""
    return f"""
      <article class="feature">
        <div class="feature-head">
          <div>
            <h2>{index}. {html.escape(feature["title"])}</h2>
            <p>{html.escape(feature["summary"])}</p>
          </div>
          <span class="badge">Для пользователей</span>
        </div>
        <div class="feature-body">
          <section>
            <h3>Как найти и использовать</h3>
            <ol>{steps}</ol>
          </section>
          <aside class="side">
            {location_blocks}
          </aside>
        </div>
        <div class="examples">
          <h3>Примеры использования</h3>
          <div class="example-grid">{examples}</div>
        </div>
        {screenshot_html}
      </article>
"""


def render_example(example: dict[str, str]) -> str:
    return f"""
            <div class="example">
              <strong>{html.escape(example.get("title", "Пример"))}</strong>
              <span>{html.escape(example.get("scenario", ""))}</span>
              <span><b>Ожидаемый результат:</b> {html.escape(example.get("expected_result", ""))}</span>
            </div>
"""


def render_empty_state() -> str:
    return """
      <article class="feature">
        <div class="feature-head">
          <div>
            <h2>Пользовательских изменений не найдено</h2>
            <p>За выбранный период агент не нашёл изменений, которые можно уверенно описать как пользовательские возможности. Попробуйте расширить период или добавить route overrides для нужных экранов.</p>
          </div>
        </div>
      </article>
"""


def build_payload(
    repos: list[Path],
    since: str,
    until: str | None,
    ref: str,
    title: str,
    max_features: int,
    *,
    audience: str,
    example_context: str,
) -> dict[str, Any]:
    all_changes: list[CommitChange] = []
    for repo in repos:
        all_changes.extend(collect_commits(repo, since, until, ref))

    scored = [(user_facing_score(change), change) for change in all_changes]
    candidates = [change for score, change in scored if score > 0 and is_publishable_change(change)]
    candidates.sort(key=lambda change: (user_facing_score(change), change.date), reverse=True)
    features = [
        build_feature(change, audience=audience, example_context=example_context)
        for change in candidates[:max_features]
    ]
    period = since if not until else f"{since} - {until}"
    return {
        "schema_version": 1,
        "title": title,
        "period": period,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repositories": [{"name": repo.name, "path": str(repo)} for repo in repos],
        "total_commits": len(all_changes),
        "features": features,
    }


def route_to_url(base_url: str, route: str, overrides: dict[str, str]) -> tuple[str, str]:
    resolved_route = overrides.get(route, route)
    if resolved_route.startswith("http://") or resolved_route.startswith("https://") or resolved_route.startswith("file://"):
        return resolved_route, resolved_route
    if ":" in resolved_route:
        return "", resolved_route
    return f"{base_url.rstrip('/')}/{resolved_route.lstrip('/')}", resolved_route


def capture_release_features(payload: dict[str, Any], config: dict[str, Any], output_dir: Path) -> None:
    ui = config.get("ui") or {}
    if not ui.get("url"):
        payload["browser_capture"] = {"status": "skipped", "reason": "ui.url is not configured"}
        return

    base_url = ui["url"]
    auth = dict(config.get("auth") or {})
    auth.update(ui.get("auth") or {})
    overrides = ui.get("route_overrides") or {}
    max_screenshots = int(ui.get("max_screenshots", 5))
    steps: list[dict[str, Any]] = []
    step_to_feature: dict[str, int] = {}

    for index, feature in enumerate(payload["features"]):
        routes = feature.get("routes") or []
        if not routes:
            continue
        target, route = route_to_url(base_url, routes[0], overrides)
        if not target:
            feature["capture"] = {
                "status": "skipped",
                "reason": f"route has unresolved parameter: {route}",
                "route": route,
            }
            continue
        step_id = f"feature-{index + 1:02d}"
        step_to_feature[step_id] = index
        steps.append(
            {
                "id": step_id,
                "action": "navigate",
                "target": target,
                "expected": f"Open feature page for {feature['title']}",
                "expected_text": ui.get("expected_text", []),
                "fail_on_missing_text": False,
                "screenshot": f"{step_id}.png",
                "capture": {"full_page": True},
                "wait_after_ms": int(ui.get("wait_after_ms", 1500)),
            }
        )
        feature["capture"] = {"status": "planned", "route": route, "target": target}
        if len(steps) >= max_screenshots:
            break

    if not steps:
        payload["browser_capture"] = {"status": "skipped", "reason": "no feature routes available for capture"}
        return

    plan = {
        "schema_version": 1,
        "run_id": payload.get("input_path") or "guidesync-release-agent",
        "ui_url": base_url,
        "auth": auth,
        "workflow_goal": "Capture release-note feature routes for user-facing guide evidence.",
        "steps": steps,
    }
    screenshots_dir = output_dir / "screenshots"
    plan_path = output_dir / "screenshot-plan.json"
    capture_path = output_dir / "browser-capture.json"
    write_json(plan_path, plan)

    ui_handle = None
    try:
        launch_result, ui_handle = launch_ui(ui)
        payload["ui_launch"] = launch_result
        run_capture(
            plan_path=plan_path,
            screenshots_dir=screenshots_dir,
            output_path=capture_path,
            headed=bool(ui.get("headed", False)),
            manual_auth=bool(ui.get("manual_auth", False)),
            auth0_token_env=auth.get("token_env"),
            storage_state=Path(auth["state_path"]) if auth.get("state_path") else None,
            env_file=Path(auth["env_file"]) if auth.get("env_file") else None,
        )
        capture_result = json.loads(capture_path.read_text(encoding="utf-8"))
        payload["browser_capture"] = {
            "status": "completed",
            "plan_path": str(plan_path),
            "capture_path": str(capture_path),
            "screenshots_dir": str(screenshots_dir),
        }
        for step in capture_result.get("steps", []):
            feature_index = step_to_feature.get(step.get("id"))
            if feature_index is None:
                continue
            capture_info = payload["features"][feature_index].setdefault("capture", {})
            capture_info["status"] = step.get("status")
            capture_info["url"] = (step.get("evidence") or {}).get("url")
            if step.get("screenshot"):
                screenshot_path = Path(step["screenshot"])
                try:
                    capture_info["screenshot"] = screenshot_path.relative_to(output_dir).as_posix()
                except ValueError:
                    capture_info["screenshot"] = str(screenshot_path)
            if step.get("error"):
                capture_info["error"] = step["error"]
    except Exception as exc:  # noqa: BLE001 - release notes should still be reviewable
        payload["browser_capture"] = {"status": "failed", "error": str(exc), "plan_path": str(plan_path)}
        for feature in payload["features"]:
            if (feature.get("capture") or {}).get("status") == "planned":
                feature["capture"]["status"] = "failed"
                feature["capture"]["error"] = str(exc)
    finally:
        cleanup_ui(ui, ui_handle)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect recent changes from repositories and generate user-facing HTML release notes with a usage guide."
    )
    parser.add_argument("--input", type=Path, help="JSON input file with repositories, period and output settings.")
    parser.add_argument("--repo", action="append", type=Path, help="Repository directory. Repeat for multiple repos.")
    parser.add_argument("--since", help="Git-compatible period start, for example '2 weeks ago' or '2026-05-01'.")
    parser.add_argument("--until", help="Optional Git-compatible period end.")
    parser.add_argument("--ref", help="Git ref to inspect. Default: HEAD.")
    parser.add_argument("--output-dir", type=Path, help="Directory for release-notes.html and release-notes.json.")
    parser.add_argument("--title", help="HTML release notes title.")
    parser.add_argument("--max-features", type=int, help="Maximum number of user-facing features to include.")
    args = parser.parse_args()

    input_path = args.input.resolve() if args.input else None
    config: dict[str, Any] = load_input(input_path) if input_path else {}
    project = config.get("project") or {}
    project_root = resolve_path(project.get("root"), input_path=input_path) if project.get("root") else None
    raw_repos = args.repo or resolve_repos(config.get("repositories", []))
    if not raw_repos:
        raise SystemExit("At least one repository is required. Use --repo or repositories[] in --input.")
    since = args.since or config.get("period", {}).get("since") or config.get("since")
    if not since:
        raise SystemExit("A period start is required. Use --since or period.since in --input.")
    until = args.until or config.get("period", {}).get("until")
    ref = args.ref or config.get("ref") or "HEAD"
    output_dir = args.output_dir or Path(config.get("output", {}).get("dir", default_output_dir(config)))
    title = args.title or config.get("output", {}).get("title") or config.get("title", "Что нового в продукте")
    max_features = args.max_features or int(config.get("max_features", 8))
    task_config = config.get("task") or {}
    audience = task_config.get("audience") or "ordinary users"
    example_context = task_config.get("example_context") or project.get("description", "")

    repos = [ensure_repo(Path(repo)) for repo in raw_repos]
    payload = build_payload(
        repos,
        since,
        until,
        ref,
        title,
        max_features,
        audience=audience,
        example_context=example_context,
    )
    if args.input:
        payload["input_path"] = str(input_path)
    payload["project"] = {
        "id": project_id_from_config(config),
        "name": project.get("name") or project_id_from_config(config),
        "description": project.get("description", ""),
    }
    payload["task"] = {
        "id": task_id_from_config(config),
        "description": (config.get("task") or {}).get("description", ""),
    }
    if config.get("auth"):
        auth_config = config["auth"]
        env_file = resolve_env_file(
            auth_config.get("env_file") or project.get("env_file"),
            input_path=input_path,
            project_root=project_root,
        )
        load_env_file(env_file)
        token_env = auth_config.get("token_env")
        if env_file:
            auth_config["env_file"] = str(env_file)
        payload["auth"] = {
            key: value
            for key, value in auth_config.items()
            if key in {"mode", "token_env", "env_file", "state_path", "role", "notes"}
        }
        if env_file:
            payload["auth"]["env_file"] = str(env_file)
        if token_env:
            payload["auth"]["token_status"] = "configured" if os.environ.get(token_env) else "missing-env"
    output_dir.mkdir(parents=True, exist_ok=True)
    capture_release_features(payload, config, output_dir)
    json_path = output_dir / "release-notes.json"
    html_path = output_dir / "release-notes.html"
    write_json(json_path, payload)
    html_path.write_text(render_html(payload), encoding="utf-8")
    print(html_path)


if __name__ == "__main__":
    main()
