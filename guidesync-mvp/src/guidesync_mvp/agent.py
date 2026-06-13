from __future__ import annotations

import argparse
import base64
import copy
import json
import mimetypes
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from jinja2 import Environment, select_autoescape

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

DEFAULT_LANGUAGE = "en"
DEFAULT_COPY_CATALOG = json.loads(
    files("guidesync_mvp").joinpath("templates/default_copy.json").read_text(encoding="utf-8")
)

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
    file_stats: list[dict[str, Any]]
    diff_hints: list[dict[str, str]]


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
        file_stats = collect_file_stats(repo, sha)
        diff_hints = collect_diff_hints(repo, sha)
        changes.append(
            CommitChange(
                repo_name=repo.name,
                repo_path=repo,
                sha=sha,
                date=date,
                subject=subject.strip(),
                body=body.strip(),
                files=files,
                file_stats=file_stats,
                diff_hints=diff_hints,
            )
        )
    return changes


def collect_file_stats(repo: Path, sha: str) -> list[dict[str, Any]]:
    raw = run_git(repo, ["show", "--numstat", "--pretty=format:", sha])
    stats: list[dict[str, Any]] = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, removed, file_path = parts[0], parts[1], parts[2]
        stats.append(
            {
                "file": file_path,
                "added": None if added == "-" else int(added),
                "removed": None if removed == "-" else int(removed),
            }
        )
    return stats


def meaningful_diff_line(line: str) -> str | None:
    stripped = line.strip()
    if len(stripped) < 6:
        return None
    if stripped.startswith((
        "import ",
        "export ",
        "from ",
        "className=",
        "style=",
        "//",
        "/*",
        "*",
    )):
        return None
    label_match = re.search(
        r"(?:title|label|placeholder|description|helperText|aria-label|name|text)\s*[:=]\s*[\"'`]([^\"'`]{4,120})",
        stripped,
    )
    if label_match:
        return label_match.group(1).strip()
    if re.search(r"<(?:Button|MenuItem|Tab|Link|Input|Select|Dialog|Modal|Tooltip|Typography|Text)", stripped):
        return re.sub(r"\s+", " ", stripped)[:160]
    if re.search(r"[A-Za-z][A-Za-z ]{8,}", stripped) and not re.search(r"[{}();]{4,}", stripped):
        return re.sub(r"\s+", " ", stripped)[:160]
    return None


def collect_diff_hints(repo: Path, sha: str) -> list[dict[str, str]]:
    raw = run_git(repo, ["show", "--format=", "--unified=0", "--no-ext-diff", "--find-renames", sha])
    hints: list[dict[str, str]] = []
    current_file = ""
    seen: set[tuple[str, str]] = set()
    for raw_line in raw.splitlines():
        if raw_line.startswith("diff --git "):
            match = re.search(r" b/(.+)$", raw_line)
            current_file = match.group(1) if match else ""
            continue
        if not current_file or is_internal_file(current_file.lower()):
            continue
        if not re.search(r"\.(tsx|jsx|vue|svelte|html|mdx|md|json|ts|js)$", current_file.lower()):
            continue
        if not raw_line.startswith("+") or raw_line.startswith("+++"):
            continue
        hint = meaningful_diff_line(raw_line[1:])
        if not hint:
            continue
        key = (current_file, hint)
        if key in seen:
            continue
        seen.add(key)
        hints.append({"file": current_file, "hint": hint})
        if len(hints) >= 16:
            break
    return hints


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


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def catalog_languages(catalog: dict[str, Any]) -> set[str]:
    languages: set[str] = set()
    for section in ("text", "release_labels", "fallback_steps", "fallback_examples", "feature_themes"):
        values = catalog.get(section) or {}
        if isinstance(values, dict):
            languages.update(str(language) for language in values.keys())
    return languages or {DEFAULT_LANGUAGE}


def catalog_value(catalog: dict[str, Any], section: str, language: str, key: str, default: str = "") -> str:
    values = catalog.get(section) or {}
    language_values = values.get(language) or values.get(DEFAULT_LANGUAGE) or {}
    if isinstance(language_values, dict):
        value = language_values.get(key)
        if value is None and language != DEFAULT_LANGUAGE:
            value = (values.get(DEFAULT_LANGUAGE) or {}).get(key)
        return str(value if value is not None else default)
    return default


def language_text(language: str, key: str, catalog: dict[str, Any] | None = None) -> str:
    return catalog_value(catalog or DEFAULT_COPY_CATALOG, "text", language, key, key)


def normalize_language(raw_language: str | None) -> str | None:
    if not raw_language:
        return None
    language = str(raw_language).strip().lower().replace("_", "-").split("-", maxsplit=1)[0]
    return language if language in catalog_languages(DEFAULT_COPY_CATALOG) else language


def normalized_language_list(raw_languages: Any) -> list[str]:
    if raw_languages is None:
        return []
    if isinstance(raw_languages, str):
        raw_values = [part.strip() for part in raw_languages.split(",")]
    elif isinstance(raw_languages, list):
        raw_values = raw_languages
    else:
        raw_values = [raw_languages]
    languages: list[str] = []
    for raw_language in raw_values:
        language = normalize_language(str(raw_language))
        if language and language not in languages:
            languages.append(language)
    return languages


def configured_languages(config: dict[str, Any]) -> list[str]:
    output = config.get("output") or {}
    task = config.get("task") or {}
    ui = config.get("ui") or {}
    project = config.get("project") or {}
    for raw_languages in (
        output.get("languages"),
        output.get("locales"),
        task.get("languages"),
        task.get("locales"),
        project.get("languages"),
        project.get("locales"),
        ui.get("languages"),
        ui.get("locales"),
    ):
        languages = normalized_language_list(raw_languages)
        if languages:
            return languages
    language = configured_language(config)
    return [language] if language else []


def configured_language(config: dict[str, Any]) -> str | None:
    output = config.get("output") or {}
    task = config.get("task") or {}
    ui = config.get("ui") or {}
    project = config.get("project") or {}
    for raw_language in (
        output.get("language"),
        output.get("locale"),
        task.get("language"),
        task.get("locale"),
        project.get("language"),
        project.get("locale"),
        ui.get("language"),
        ui.get("locale"),
    ):
        language = normalize_language(raw_language)
        if language:
            return language
    return None


def infer_language_from_text(text: str) -> str | None:
    normalized = text.lower()
    keywords = DEFAULT_COPY_CATALOG.get("ui_language_keywords") or {}
    scores = {
        language: sum(1 for keyword in keywords if keyword in normalized)
        for language, keywords in keywords.items()
    }
    if not scores:
        return None
    best_language, best_score = max(scores.items(), key=lambda item: item[1])
    return best_language if best_score >= 2 else None


def detect_guide_language(config: dict[str, Any], payload: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    configured = configured_language(config)
    signals: list[dict[str, str]] = []
    if configured:
        signals.append({"source": "input", "value": configured, "language": configured})
        return configured, signals

    for feature in payload.get("features", []):
        capture = feature.get("capture") or {}
        for source in ("html_lang", "navigator_language"):
            language = normalize_language(capture.get(source))
            if language:
                signals.append({"source": source, "value": str(capture[source]), "language": language})
                return language, signals
        detected = normalize_language(capture.get("detected_language"))
        if detected:
            signals.append({"source": "visible_text", "value": detected, "language": detected})
            return detected, signals

    return DEFAULT_LANGUAGE, signals or [{"source": "default", "value": DEFAULT_LANGUAGE, "language": DEFAULT_LANGUAGE}]


def user_facing_title(raw_title: str, features: list[str], routes: list[str], language: str) -> str:
    text = " ".join([raw_title, *features, *routes]).lower()
    for pattern in DEFAULT_COPY_CATALOG.get("title_patterns", []):
        needles = pattern.get("needles") or []
        titles = pattern.get("title") or {}
        if all(needle in text for needle in needles):
            return titles.get(language) or titles.get(DEFAULT_LANGUAGE) or raw_title
    cleaned = re.sub(r"\s*\(#\d+\)\s*$", "", raw_title).strip()
    cleaned = re.sub(r"^(add|implement|support|create|update)\s+", "", cleaned, flags=re.I).strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else raw_title


def low_signal_change_title(title: str) -> bool:
    normalized = title.strip().lower()
    if re.search(r"\b[A-Z]{2,12}-\d+\b", title):
        return True
    if re.search(r"\bpull request #?\d+\b", normalized):
        return True
    if normalized in {"fix", "bugfix", "changes", "updates", "improvements"}:
        return True
    if re.fullmatch(r"[a-z]{2,12}-\d+\s+fix", normalized):
        return True
    return False


def change_evidence(change: CommitChange) -> dict[str, Any]:
    non_internal_stats = [
        stat for stat in change.file_stats if not is_internal_file(str(stat.get("file", "")).lower())
    ]
    return {
        "repo": change.repo_name,
        "commit": change.sha,
        "short_commit": change.sha[:8],
        "date": change.date,
        "subject": change.subject,
        "body": change.body,
        "files": [file_path for file_path in change.files if not is_internal_file(file_path.lower())],
        "file_stats": non_internal_stats[:30],
        "diff_hints": change.diff_hints,
    }


def copy_status_for_change(
    technical_title: str,
    title: str,
    routes: list[str],
    features: list[str],
    copy_block: dict[str, Any] | None,
    diff_hints: list[dict[str, str]],
) -> dict[str, Any]:
    if copy_block:
        return {
            "status": "ready",
            "source": "project-copy-catalog",
            "reason": "Matched a known product feature pattern with curated user-facing copy.",
        }
    if low_signal_change_title(technical_title):
        return {
            "status": "agent_required",
            "source": "git-evidence",
            "reason": "Commit title is an issue/PR label or otherwise too vague for direct user-facing copy.",
        }
    if not routes and not diff_hints:
        return {
            "status": "agent_required",
            "source": "git-evidence",
            "reason": "No route, known interaction recipe, or readable diff hint was found.",
        }
    if not features and not routes:
        return {
            "status": "agent_required",
            "source": "git-evidence",
            "reason": "The changed files do not identify a stable product area.",
        }
    return {
        "status": "heuristic_draft",
        "source": "git-and-ui-heuristics",
        "reason": "Generated from file paths, route hints and readable diff hints; agent review should rewrite before publishing.",
    }


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


def display_area(area: str, language: str) -> str:
    label = (DEFAULT_COPY_CATALOG.get("area_labels") or {}).get(area)
    if label:
        return label.get(language) or label.get(DEFAULT_LANGUAGE) or area
    return area.replace("-", " ").replace("_", " ")


def display_route(route: str, language: str) -> str:
    if route == "/":
        return language_text(language, "home_page")
    cleaned = route.strip("/")
    if not cleaned:
        return language_text(language, "home_page")
    return " / ".join(part.replace(":", "").replace("-", " ") for part in cleaned.split("/"))


def display_audience(audience: str, language: str) -> str:
    lowered = audience.lower().strip()
    if lowered in {"ordinary users", "regular users", "ordinary ardor users"}:
        return language_text(language, "ordinary_user")
    return audience


def feature_copy_key(title: str, routes: list[str], features: list[str]) -> str | None:
    text = " ".join([title, *routes, *features]).lower()
    if "domain" in text:
        return "domains"
    if "resource" in text and "mention" in text:
        return "resource_mentions"
    if "slash" in text and "command" in text:
        return "slash_commands"
    if "workspace" in text and ("permission" in text or "access" in text):
        return "workspace_permissions"
    return None


def feature_copy(title: str, routes: list[str], features: list[str], language: str) -> dict[str, Any] | None:
    key = feature_copy_key(title, routes, features)
    if not key:
        return None
    copies = (DEFAULT_COPY_CATALOG.get("feature_copy") or {}).get(key) or {}
    return copies.get(language) or copies.get(DEFAULT_LANGUAGE)


def display_location(title: str, routes: list[str], features: list[str], language: str) -> str:
    copy_block = feature_copy(title, routes, features, language)
    if copy_block and copy_block.get("location"):
        return str(copy_block["location"])
    if routes:
        return display_route(routes[0], language)
    if features:
        return display_area(features[0], language)
    return language_text(language, "unknown_location")


def usage_steps(title: str, routes: list[str], features: list[str], language: str) -> list[str]:
    copy_block = feature_copy(title, routes, features, language)
    if copy_block and copy_block.get("steps"):
        return list(copy_block["steps"])
    group = "with_route" if routes else "with_area" if features else "unknown"
    templates = (DEFAULT_COPY_CATALOG.get("fallback_steps") or {}).get(language) or (
        DEFAULT_COPY_CATALOG.get("fallback_steps") or {}
    ).get(DEFAULT_LANGUAGE, {})
    return [
        str(template).format(title=title, location=display_location(title, routes, features, language))
        for template in templates.get(group, [])
    ]


def usage_examples(
    title: str,
    routes: list[str],
    features: list[str],
    audience: str,
    example_context: str,
    language: str,
) -> list[dict[str, str]]:
    copy_block = feature_copy(title, routes, features, language)
    if copy_block and copy_block.get("examples"):
        return list(copy_block["examples"])
    location = display_location(title, routes, features, language)
    cleaned_context = example_context.strip().rstrip(".")
    skip_generic_context = cleaned_context.lower().startswith("use examples")
    context_prefix = f"{cleaned_context}. " if cleaned_context and not skip_generic_context else ""
    readable_audience = display_audience(audience, language)
    templates = (DEFAULT_COPY_CATALOG.get("fallback_examples") or {}).get(language) or (
        DEFAULT_COPY_CATALOG.get("fallback_examples") or {}
    ).get(DEFAULT_LANGUAGE, [])
    return [
        {
            key: str(value).format(
                audience=readable_audience,
                audience_capitalized=readable_audience.capitalize(),
                context_prefix=context_prefix,
                location=location,
                title=title,
            )
            for key, value in template.items()
        }
        for template in templates
    ]


def build_feature(change: CommitChange, *, audience: str, example_context: str, language: str) -> dict[str, Any]:
    routes = route_hints(change.files)
    features = feature_hints(change.files)
    evidence_files = [file_path for file_path in change.files if not is_internal_file(file_path.lower())]
    technical_title = human_title(change.subject)
    title = user_facing_title(technical_title, features, routes, language)
    copy_block = feature_copy(title, routes, features, language)
    if copy_block and copy_block.get("title"):
        title = str(copy_block["title"])
    copy_status = copy_status_for_change(technical_title, title, routes, features, copy_block, change.diff_hints)
    return {
        "title": title,
        "technical_title": technical_title,
        "summary": summarise_change(title, routes, features, language),
        "benefit": feature_benefit(title, routes, features, language),
        "repo": change.repo_name,
        "commit": change.sha[:8],
        "date": change.date,
        "routes": routes,
        "areas": features,
        "steps": usage_steps(title, routes, features, language),
        "examples": usage_examples(title, routes, features, audience, example_context, language),
        "files": evidence_files[:12],
        "source_evidence": change_evidence(change),
        "copy_status": copy_status,
        "score": user_facing_score(change),
    }


def summarise_change(title: str, routes: list[str], features: list[str], language: str) -> str:
    copy_block = feature_copy(title, routes, features, language)
    if copy_block and copy_block.get("summary"):
        return str(copy_block["summary"])
    if routes:
        template_key = "summary_with_route"
        location = display_location(title, routes, features, language)
    elif features:
        template_key = "summary_with_area"
        location = display_location(title, routes, features, language)
    else:
        template_key = "summary_unknown"
        location = display_location(title, routes, features, language)
    return language_text(language, template_key).format(title=title, location=location)


def feature_benefit(title: str, routes: list[str], features: list[str], language: str) -> str:
    copy_block = feature_copy(title, routes, features, language)
    if copy_block and copy_block.get("benefit"):
        return str(copy_block["benefit"])
    return language_text(language, "benefit").format(title=title)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_input(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_project_defaults(config: dict[str, Any], input_path: Path | None) -> dict[str, Any]:
    if not input_path:
        return config
    project_file = input_path.parent / "project.json"
    if not project_file.exists() or input_path.name == "project.json":
        return config
    defaults = load_input(project_file)
    project_defaults = defaults.get("project") or {}
    merged = copy.deepcopy(config)
    merged["project"] = deep_merge(project_defaults, merged.get("project") or {})
    raw_defaults = defaults.get("defaults") or {}
    if raw_defaults.get("ref") and not merged.get("ref"):
        merged["ref"] = raw_defaults["ref"]
    ui_defaults = raw_defaults.get("ui") or {}
    if raw_defaults.get("ui_url"):
        ui_defaults = deep_merge({"url": raw_defaults["ui_url"]}, ui_defaults)
    if ui_defaults:
        merged["ui"] = deep_merge(ui_defaults, merged.get("ui") or {})
    output_root = raw_defaults.get("output_root")
    if output_root:
        output = merged.setdefault("output", {})
        output.setdefault("root", output_root)
    return merged


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


def resolve_project_asset(raw_path: str | Path | None, *, input_path: Path | None, project_root: Path | None = None) -> Path | None:
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


def file_data_uri(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def load_branding(config: dict[str, Any], *, input_path: Path | None, project_root: Path | None) -> dict[str, Any]:
    project = config.get("project") or {}
    raw_branding = config.get("branding") or project.get("branding") or {}
    branding: dict[str, Any] = {
        "name": raw_branding.get("name") or project.get("name", ""),
        "css": "",
        "logo_data_uri": "",
        "logo_path": "",
    }
    css_path = resolve_project_asset(
        raw_branding.get("css_file") or raw_branding.get("css_path"),
        input_path=input_path,
        project_root=project_root,
    )
    if css_path and css_path.exists():
        branding["css"] = css_path.read_text(encoding="utf-8")
        branding["css_path"] = str(css_path)
    logo_path = resolve_project_asset(
        raw_branding.get("logo_file") or raw_branding.get("logo_path"),
        input_path=input_path,
        project_root=project_root,
    )
    if logo_path and logo_path.exists():
        branding["logo_data_uri"] = file_data_uri(logo_path)
        branding["logo_path"] = str(logo_path)
    return branding


def load_copy_catalog(config: dict[str, Any], *, input_path: Path | None, project_root: Path | None) -> dict[str, Any]:
    project = config.get("project") or {}
    raw_copy = config.get("copy") or project.get("copy") or {}
    catalog = copy.deepcopy(DEFAULT_COPY_CATALOG)
    copy_file = resolve_project_asset(
        raw_copy.get("catalog_file") or raw_copy.get("file"),
        input_path=input_path,
        project_root=project_root,
    )
    if copy_file and copy_file.exists():
        catalog = deep_merge(catalog, json.loads(copy_file.read_text(encoding="utf-8")))
    inline_catalog = raw_copy.get("catalog")
    if isinstance(inline_catalog, dict):
        catalog = deep_merge(catalog, inline_catalog)
    return catalog


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


def release_notes_template() -> Any:
    template_text = files("guidesync_mvp").joinpath("templates/release_notes.html").read_text(encoding="utf-8")
    environment = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
    return environment.from_string(template_text)


def title_for_language(payload: dict[str, Any], language: str) -> str:
    title = str(payload.get("title") or "").strip()
    project = payload.get("project") or {}
    project_name = project.get("name") or "the product"
    if language == DEFAULT_LANGUAGE and re.search(r"[^\x00-\x7f]", title):
        return f"What's new in {project_name}"
    if not title:
        return language_text(language, "default_title")
    return title


def localize_payload(payload: dict[str, Any], *, language: str, audience: str, example_context: str) -> None:
    payload["language"] = language
    payload["title"] = title_for_language(payload, language)
    for feature in payload.get("features", []):
        technical_title = feature.get("technical_title") or feature.get("title") or ""
        routes = feature.get("routes") or []
        areas = feature.get("areas") or []
        title = user_facing_title(str(technical_title), areas, routes, language)
        copy_block = feature_copy(title, routes, areas, language)
        if copy_block and copy_block.get("title"):
            title = str(copy_block["title"])
        feature["title"] = title
        feature["summary"] = summarise_change(title, routes, areas, language)
        feature["benefit"] = feature_benefit(title, routes, areas, language)
        feature["steps"] = usage_steps(title, routes, areas, language)
        feature["examples"] = usage_examples(title, routes, areas, audience, example_context, language)


def announcement_headline(payload: dict[str, Any], language: str) -> str:
    project = (payload.get("project") or {}).get("name") or "the product"
    return language_text(language, "announcement_headline").format(project=project)


def announcement_subtitle(payload: dict[str, Any], language: str) -> str:
    return language_text(language, "announcement_subtitle")


def announcement_eyebrow(payload: dict[str, Any], language: str) -> str:
    period = payload.get("period") or ""
    return language_text(language, "announcement_eyebrow").format(period=period)


def takeaways(features: list[dict[str, Any]], language: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for feature in features[:4]:
        items.append(
            {
                "title": str(feature.get("title", "")),
                "body": str(feature.get("benefit") or feature.get("summary", "")),
            }
        )
    return items


def feature_announcement_score(feature: dict[str, Any]) -> int:
    score = int(feature.get("score", 0))
    capture = feature.get("capture") or {}
    if feature.get("routes"):
        score += 35
    if capture.get("screenshot"):
        score += 40
    if capture.get("status") == "failed":
        score -= 60
    if capture.get("mode") == "route":
        score += 12
    if capture.get("mode") == "interaction":
        score += 8
    if feature.get("benefit"):
        score += 10
    if feature.get("examples"):
        score += 8
    if feature.get("steps"):
        score += 6
    summary_text = " ".join(str(feature.get(key, "")) for key in ("title", "summary", "benefit")).lower()
    outcome_terms = (
        "share",
        "publish",
        "faster",
        "quicker",
        "protect",
        "control",
        "context",
        "discover",
        "reduce",
        "easier",
        "brand",
    )
    score += min(18, sum(3 for term in outcome_terms if term in summary_text))
    return score


def feature_priority_reasons(feature: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    capture = feature.get("capture") or {}
    if capture.get("screenshot"):
        reasons.append("has a usable UI screenshot")
    if feature.get("routes"):
        reasons.append("has a concrete UI route")
    if capture.get("mode") == "interaction":
        reasons.append("was captured through a UI interaction")
    if feature.get("benefit"):
        reasons.append("explains user benefit")
    if feature.get("examples"):
        reasons.append("has usage examples")
    if capture.get("status") == "failed":
        reasons.append("capture failed, so it is lower priority until fixed")
    if not reasons:
        reasons.append("ranked from change score and inferred user-facing impact")
    return reasons


def assign_announcement_priorities(payload: dict[str, Any]) -> None:
    features = [feature for feature in payload.get("features", []) if is_user_visible_feature(feature)]
    ranked = sorted(features, key=feature_sort_key)
    for rank, feature in enumerate(ranked, start=1):
        feature["announcement_priority"] = {
            "rank": rank,
            "role": "spotlight" if rank == 1 else "supporting",
            "score": feature_announcement_score(feature),
            "reasons": feature_priority_reasons(feature),
        }
    payload["announcement_priority"] = {
        "strategy": "Rank by user-facing outcome, successful UI evidence, completeness of examples/steps, and source change score.",
        "ranked_features": [
            {
                "rank": feature["announcement_priority"]["rank"],
                "title": feature.get("title"),
                "role": feature["announcement_priority"]["role"],
                "score": feature["announcement_priority"]["score"],
                "reasons": feature["announcement_priority"]["reasons"],
            }
            for feature in ranked
        ],
    }


def feature_sort_key(feature: dict[str, Any]) -> tuple[int, int]:
    priority = feature.get("announcement_priority") or {}
    if priority.get("rank"):
        return (int(priority["rank"]), 0)
    return (-feature_announcement_score(feature), -int(feature.get("score", 0)))


def is_user_visible_feature(feature: dict[str, Any]) -> bool:
    copy_status = feature.get("copy_status") or {}
    if copy_status.get("status") == "agent_required":
        return False
    capture = feature.get("capture") or {}
    return bool(feature.get("routes") or feature.get("areas") or capture.get("status") == "ok")


def spotlight_feature(features: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not features:
        return None
    for feature in features:
        if (feature.get("announcement_priority") or {}).get("role") == "spotlight":
            return feature
    return sorted(features, key=feature_sort_key)[0]


def feature_theme(feature: dict[str, Any], language: str) -> str:
    key = feature_copy_key(str(feature.get("title", "")), feature.get("routes", []), feature.get("areas", []))
    themes = (DEFAULT_COPY_CATALOG.get("feature_themes") or {}).get(language) or (
        DEFAULT_COPY_CATALOG.get("feature_themes") or {}
    ).get(DEFAULT_LANGUAGE, {})
    return themes.get(key or "", themes.get("default", "Improvement"))


def release_notes_labels(language: str) -> dict[str, str]:
    labels = copy.deepcopy((DEFAULT_COPY_CATALOG.get("release_labels") or {}).get(DEFAULT_LANGUAGE, {}))
    labels.update((DEFAULT_COPY_CATALOG.get("release_labels") or {}).get(language, {}))
    labels.update(
        {
            "empty_body": language_text(language, "empty_body"),
            "empty_title": language_text(language, "empty_title"),
            "expected": language_text(language, "expected"),
            "how": language_text(language, "how"),
            "why": language_text(language, "why"),
        }
    )
    return labels


def render_html(payload: dict[str, Any]) -> str:
    return release_notes_template().render(**release_notes_view_model(payload))


def release_notes_view_model(payload: dict[str, Any]) -> dict[str, Any]:
    language = normalize_language(payload.get("language")) or "en"
    features = sorted(
        [feature for feature in payload["features"] if is_user_visible_feature(feature)],
        key=feature_sort_key,
    )
    spotlight = spotlight_feature(features)
    supporting = [feature for feature in features if feature is not spotlight]
    return {
        "language": language,
        "title": payload.get("title") or title_for_language(payload, language),
        "branding": payload.get("branding") or {},
        "eyebrow": announcement_eyebrow(payload, language),
        "headline": announcement_headline(payload, language),
        "subtitle": announcement_subtitle(payload, language),
        "takeaways": takeaways(features, language),
        "spotlight": spotlight,
        "supporting": supporting,
        "labels": release_notes_labels(language),
        "feature_theme": feature_theme,
    }


def review_release_notes(payload: dict[str, Any]) -> dict[str, Any]:
    language = normalize_language(payload.get("language")) or "en"
    html_output = render_html(payload)
    findings: list[dict[str, str]] = []
    generic_phrases = (
        "adds or improves",
        "visible headings, buttons, or helper text",
        "where they previously needed a workaround",
        "agent / sessionId",
        "confirmed in the live UI",
        "copy check",
        "Draft release notes",
        "src/",
        "commit",
    )
    for phrase in generic_phrases:
        if phrase in html_output:
            findings.append(
                {
                    "severity": "needs-fix",
                    "check": "user-copy",
                    "message": f"User-facing HTML still contains generic or technical wording: {phrase}",
                }
            )
    if 'class="hero"' not in html_output:
        findings.append(
            {
                "severity": "needs-fix",
                "check": "announcement-structure",
                "message": "User-facing HTML does not include a hero announcement section.",
            }
        )
    if 'class="cta"' not in html_output:
        findings.append(
            {
                "severity": "needs-fix",
                "check": "announcement-structure",
                "message": "User-facing HTML does not include a clear try-it-now CTA.",
            }
        )
    if "spotlight" not in html_output:
        findings.append(
            {
                "severity": "needs-fix",
                "check": "announcement-structure",
                "message": "User-facing HTML does not include a spotlight feature.",
            }
        )
    for feature in payload.get("features", []):
        copy_status = feature.get("copy_status") or {}
        if copy_status.get("status") == "agent_required":
            findings.append(
                {
                    "severity": "needs-agent-copy",
                    "check": "source-evidence",
                    "message": f"{feature.get('technical_title') or feature.get('title', 'Feature')} needs agent-written copy from commit and diff evidence before it is publishable.",
                }
            )
            continue
        has_ui_surface = bool(feature.get("routes") or feature.get("areas") or feature_copy_key(str(feature.get("title", "")), feature.get("routes", []), feature.get("areas", [])))
        if not feature.get("benefit"):
            findings.append(
                {
                    "severity": "needs-fix",
                    "check": "benefit",
                    "message": f"{feature.get('title', 'Feature')} does not explain why a user should care.",
                }
            )
        if not feature.get("examples"):
            findings.append(
                {
                    "severity": "needs-fix",
                    "check": "examples",
                    "message": f"{feature.get('title', 'Feature')} has no usage examples.",
                }
            )
        if has_ui_surface and not (feature.get("capture") or {}).get("screenshot"):
            findings.append(
                {
                    "severity": "needs-fix",
                    "check": "screenshot",
                    "message": f"{feature.get('title', 'Feature')} has a UI surface but no captured screenshot.",
                }
            )
    return {
        "status": "passed" if not findings else "needs-review",
        "language": language,
        "findings": findings,
    }


def render_agent_report(payload: dict[str, Any], output_dir: Path, artifacts: dict[str, str]) -> str:
    project = payload.get("project") or {}
    task = payload.get("task") or {}
    review = payload.get("content_review") or {}
    browser_capture = payload.get("browser_capture") or {}
    features = payload.get("features") or []
    lines = [
        f"# GuideSync agent report: {project.get('name', project.get('id', 'project'))} {task.get('id', 'release-notes')}",
        "",
        f"Generated: {payload.get('generated_at', '')[:10]}",
        "",
        "## What The Agent Did",
        "",
        f"- Analyzed {payload.get('total_commits', 0)} commits across {len(payload.get('repositories', []))} repositories.",
        f"- Selected {len(features)} likely user-facing changes for release notes.",
        f"- Generated release notes in: {', '.join(payload.get('language_detection', {}).get('languages', [payload.get('language', 'en')]))}.",
        f"- Browser capture status: {browser_capture.get('status', 'unknown')}.",
        f"- Content review status: {review.get('status', 'unknown')}.",
        "",
        "## Output Artifacts",
        "",
    ]
    for name, path in artifacts.items():
        lines.append(f"- `{name}`: `{path}`")

    lines.extend(["", "## Included Updates", ""])
    publishable_features = [feature for feature in features if is_user_visible_feature(feature)]
    if publishable_features:
        for index, feature in enumerate(sorted(publishable_features, key=feature_sort_key), start=1):
            capture = feature.get("capture") or {}
            priority = feature.get("announcement_priority") or {}
            screenshot = "with screenshot" if capture.get("screenshot") else "no screenshot"
            role = priority.get("role", "supporting")
            score = priority.get("score", feature_announcement_score(feature))
            reasons = "; ".join(priority.get("reasons", []))
            lines.append(f"{index}. {feature.get('title', 'Untitled')} - {role}, {screenshot}, priority score {score}")
            if reasons:
                lines.append(f"   Priority rationale: {reasons}")
    else:
        lines.append("No user-facing updates were selected.")

    evidence_only_features = [
        feature for feature in features if (feature.get("copy_status") or {}).get("status") == "agent_required"
    ]
    if evidence_only_features:
        lines.extend(["", "## Evidence-Only Candidates", ""])
        lines.append(
            "These changes were kept out of the user-facing HTML because the script only found low-signal technical labels. Use `change-evidence.json` and `source_evidence` to write copy manually."
        )
        lines.append("")
        for feature in evidence_only_features:
            status = feature.get("copy_status") or {}
            evidence = feature.get("source_evidence") or {}
            lines.append(
                f"- {evidence.get('repo', feature.get('repo'))} {evidence.get('short_commit', feature.get('commit'))}: {evidence.get('subject', feature.get('technical_title'))} — {status.get('reason')}"
            )

    lines.extend(["", "## Problems And Warnings", ""])
    problems: list[str] = []
    auth = payload.get("auth") or {}
    if auth.get("token_status") == "missing-env":
        problems.append(f"Auth token `{auth.get('token_env')}` was not found in the configured environment.")
    if browser_capture.get("status") not in {"completed", "skipped"}:
        problems.append(f"Browser capture did not complete: {browser_capture.get('error', browser_capture.get('status'))}")
    for feature in features:
        capture = feature.get("capture") or {}
        if capture.get("status") == "failed":
            problems.append(f"Capture failed for {feature.get('title')}: {capture.get('error', 'unknown error')}")
    for finding in review.get("findings", []):
        if finding.get("severity") in {"needs-fix", "warning", "needs-agent-copy"}:
            problems.append(f"{finding.get('severity')}: {finding.get('message')}")
    if problems:
        lines.extend(f"- {problem}" for problem in problems)
    else:
        lines.append("- No blocking problems were detected.")

    missing_ui_screenshots = [
        feature.get("title", "Untitled")
        for feature in features
        if (feature.get("routes") or feature.get("areas"))
        and not (feature.get("capture") or {}).get("screenshot")
    ]
    if missing_ui_screenshots:
        lines.extend(
            [
                "",
                "## Screenshot Coverage Gap",
                "",
                "The release planner must capture screenshots for UI-visible changes even when the change did not introduce a new route. Route-less UI changes should use interaction-based Playwright steps such as typing `/` or `@` in the chat composer, opening menus, or navigating to an existing settings page.",
                "",
            ]
        )
        lines.extend(f"- Missing UI screenshot: {title}" for title in missing_ui_screenshots)

    lines.extend(
        [
            "",
            "## Review Notes",
            "",
            "The HTML is intended for a user-facing release mailing. Technical evidence such as commit ids and changed files remains in `release-notes.json` for audit/debugging, not in the HTML.",
            "",
        ]
    )
    return "\n".join(lines)


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
    language: str,
) -> dict[str, Any]:
    all_changes: list[CommitChange] = []
    for repo in repos:
        all_changes.extend(collect_commits(repo, since, until, ref))

    scored = [(user_facing_score(change), change) for change in all_changes]
    candidates = [change for score, change in scored if score > 0 and is_publishable_change(change)]
    candidates.sort(key=lambda change: (user_facing_score(change), change.date), reverse=True)
    selected_changes = candidates[:max_features]
    selected_commits = {change.sha for change in selected_changes}
    features = [
        build_feature(change, audience=audience, example_context=example_context, language=language)
        for change in selected_changes
    ]
    period = since if not until else f"{since} - {until}"
    return {
        "schema_version": 1,
        "title": title,
        "period": period,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": language,
        "repositories": [{"name": repo.name, "path": str(repo)} for repo in repos],
        "total_commits": len(all_changes),
        "change_evidence": {
            "purpose": "Machine-readable source facts for the agent. Use this to write user-facing copy; do not publish commit subjects directly.",
            "period": period,
            "ref": ref,
            "commits": [
                {
                    **change_evidence(change),
                    "score": score,
                    "publishable_candidate": change in candidates,
                    "selected_for_release_notes": change.sha in selected_commits,
                    "routes": route_hints(change.files),
                    "areas": feature_hints(change.files),
                }
                for score, change in sorted(scored, key=lambda item: (item[0], item[1].date), reverse=True)
                if score > 0
            ],
        },
        "features": features,
    }


def route_to_url(base_url: str, route: str, overrides: dict[str, str]) -> tuple[str, str]:
    resolved_route = overrides.get(route, route)
    if resolved_route.startswith("http://") or resolved_route.startswith("https://") or resolved_route.startswith("file://"):
        return resolved_route, resolved_route
    if ":" in resolved_route:
        return "", resolved_route
    return f"{base_url.rstrip('/')}/{resolved_route.lstrip('/')}", resolved_route


def feature_capture_steps(
    feature: dict[str, Any],
    *,
    index: int,
    base_url: str,
    overrides: dict[str, str],
    ui: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    wait_after_ms = int(ui.get("wait_after_ms", 1500))
    expected_text = ui.get("expected_text", [])
    reject_text = ["404", "Page not found", "Whoops!"]
    clip_defaults = {
        "domains": {"x": 900, "y": 110, "width": 480, "height": 840},
        "chat": {"x": 300, "y": 190, "width": 620, "height": 360},
        "settings": {"x": 300, "y": 80, "width": 900, "height": 820},
    }
    clip_defaults.update(ui.get("capture_clips") or {})
    routes = feature.get("routes") or []
    if routes:
        target, route = route_to_url(base_url, routes[0], overrides)
        if not target:
            return [], {
                "status": "skipped",
                "reason": f"route has unresolved parameter: {route}",
                "route": route,
            }
        step_id = f"feature-{index + 1:02d}"
        key = feature_copy_key(str(feature.get("title", "")), routes, feature.get("areas", []))
        required_text = ["Domains", "Add domain"] if key == "domains" else []
        return [
            {
                "id": step_id,
                "action": "navigate",
                "target": target,
                "expected": f"Open feature page for {feature['title']}",
                "expected_text": expected_text,
                "reject_text": reject_text,
                "required_text": required_text,
                "fail_on_missing_text": False,
                "screenshot": f"{step_id}.png",
                "capture": {
                    "full_page": True,
                    "clip": clip_defaults["domains"] if key == "domains" else None,
                    "highlight_selector": "text=Add domain" if key == "domains" else None,
                },
                "wait_after_ms": wait_after_ms,
                "retries": [
                    {
                        "target": target,
                        "screenshot": f"{step_id}-retry-{retry_index}.png",
                        "wait_after_ms": retry_wait,
                    }
                    for retry_index, retry_wait in enumerate((3000, 5000), start=1)
                ]
                if key == "domains"
                else [],
            }
        ], {"status": "planned", "route": route, "target": target, "mode": "route"}

    key = feature_copy_key(str(feature.get("title", "")), [], feature.get("areas", []))
    home_route = str(ui.get("home_route") or overrides.get("/") or "/agent")
    target, route = route_to_url(base_url, home_route, overrides)
    placeholders = ui.get("chat_input_placeholders") or []
    chat_selectors = ui.get("chat_input_selectors") or ['[contenteditable="true"][role="combobox"]']
    if key == "slash_commands":
        step_id = f"feature-{index + 1:02d}-slash-command"
        return [
            {
                "id": step_id,
                "action": "fill",
                "target": target,
                "selectors": chat_selectors,
                "placeholders": placeholders,
                "role": ui.get("chat_input_role", "combobox"),
                "value": "/",
                "expected": "Open slash command suggestions from the chat composer.",
                "expected_text": expected_text,
                "reject_text": reject_text,
                "fail_on_missing_text": False,
                "screenshot": f"{step_id}.png",
                "capture": {"full_page": True, "clip": clip_defaults["chat"]},
                "wait_after_ms": wait_after_ms,
            }
        ], {"status": "planned", "route": route, "target": target, "mode": "interaction", "interaction": "type-slash"}
    if key == "resource_mentions":
        step_id = f"feature-{index + 1:02d}-resource-mention"
        return [
            {
                "id": step_id,
                "action": "fill",
                "target": target,
                "selectors": chat_selectors,
                "placeholders": placeholders,
                "role": ui.get("chat_input_role", "combobox"),
                "value": "@",
                "expected": "Open resource mention suggestions from the chat composer.",
                "expected_text": expected_text,
                "reject_text": reject_text,
                "fail_on_missing_text": False,
                "screenshot": f"{step_id}.png",
                "capture": {"full_page": True, "clip": clip_defaults["chat"]},
                "wait_after_ms": wait_after_ms,
            }
        ], {"status": "planned", "route": route, "target": target, "mode": "interaction", "interaction": "type-at"}
    if key == "workspace_permissions":
        settings_route = str(ui.get("settings_route") or "/agent/new/settings/workspace/team")
        target, route = route_to_url(base_url, settings_route, overrides)
        step_id = f"feature-{index + 1:02d}-workspace-access"
        retry_routes = ui.get("settings_retry_routes") or [
            "/agent/new/settings/workspace/general",
            "/agent/new/settings/workspace/billing",
            "/agent",
        ]
        return [
            {
                "id": step_id,
                "action": "navigate",
                "target": target,
                "expected": "Open workspace settings or account menu area for access controls.",
                "expected_text": expected_text,
                "reject_text": reject_text,
                "required_any_text": ["Team", "Invite people", "Members", "Workspace"],
                "fail_on_missing_text": False,
                "screenshot": f"{step_id}.png",
                "capture": {"full_page": True, "clip": clip_defaults["settings"]},
                "wait_after_ms": wait_after_ms,
                "retries": [
                    {
                        "target": route_to_url(base_url, retry_route, overrides)[0],
                        "screenshot": f"{step_id}-retry-{retry_index}.png",
                        "capture": {"full_page": True, "clip": clip_defaults["settings"]},
                    }
                    for retry_index, retry_route in enumerate(retry_routes, start=1)
                ],
            }
        ], {"status": "planned", "route": route, "target": target, "mode": "interaction", "interaction": "workspace-settings"}

    return [], {"status": "skipped", "reason": "no route or known interaction capture recipe"}


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

    feature_order = sorted(range(len(payload["features"])), key=lambda item: feature_sort_key(payload["features"][item]))
    for index in feature_order:
        feature = payload["features"][index]
        planned_steps, capture_info = feature_capture_steps(
            feature,
            index=index,
            base_url=base_url,
            overrides=overrides,
            ui=ui,
        )
        if capture_info:
            feature["capture"] = capture_info
        if not planned_steps:
            continue
        for step in planned_steps:
            step_to_feature[str(step["id"])] = index
            steps.append(step)
        if len(steps) >= max_screenshots:
            break

    if not steps:
        payload["browser_capture"] = {"status": "skipped", "reason": "no feature routes or interaction recipes available for capture"}
        return

    plan = {
        "schema_version": 1,
        "run_id": payload.get("input_path") or "guidesync-release-agent",
        "ui_url": base_url,
        "auth": auth,
        "workflow_goal": "Capture release-note feature routes and interaction states for user-facing guide evidence.",
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
            evidence = step.get("evidence") or {}
            capture_info["status"] = step.get("status")
            capture_info["url"] = evidence.get("url")
            for key in ("html_lang", "navigator_language"):
                if evidence.get(key):
                    capture_info[key] = evidence[key]
            detected_language = infer_language_from_text(
                "\n".join(str(evidence.get(key, "")) for key in ("html_lang", "navigator_language", "title", "visible_text"))
            )
            if detected_language:
                capture_info["detected_language"] = detected_language
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
    config = load_project_defaults(config, input_path)
    project = config.get("project") or {}
    project_root = resolve_path(project.get("root"), input_path=input_path) if project.get("root") else None
    raw_repos = args.repo or resolve_repos(config.get("repositories", []))
    if not raw_repos:
        raise SystemExit("At least one repository is required. Use --repo or repositories[] in --input.")
    global DEFAULT_COPY_CATALOG
    DEFAULT_COPY_CATALOG = load_copy_catalog(config, input_path=input_path, project_root=project_root)
    since = args.since or config.get("period", {}).get("since") or config.get("since")
    if not since:
        raise SystemExit("A period start is required. Use --since or period.since in --input.")
    until = args.until or config.get("period", {}).get("until")
    ref = args.ref or config.get("ref") or "HEAD"
    output_dir = args.output_dir or Path(config.get("output", {}).get("dir", default_output_dir(config)))
    explicit_languages = configured_languages(config)
    initial_language = DEFAULT_LANGUAGE
    title = args.title or config.get("output", {}).get("title") or config.get("title", language_text(initial_language, "default_title"))
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
        language=initial_language,
    )
    if args.input:
        payload["input_path"] = str(input_path)
    payload["project"] = {
        "id": project_id_from_config(config),
        "name": project.get("name") or project_id_from_config(config),
        "description": project.get("description", ""),
    }
    payload["branding"] = load_branding(config, input_path=input_path, project_root=project_root)
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
    detected_language, language_signals = detect_guide_language(config, payload)
    requested_languages = explicit_languages or [DEFAULT_LANGUAGE]
    output_languages = [DEFAULT_LANGUAGE]
    for language in requested_languages:
        if language not in output_languages:
            output_languages.append(language)
    if detected_language not in output_languages and explicit_languages:
        output_languages.append(detected_language)
    payload["language_detection"] = {
        "language": output_languages[0],
        "languages": output_languages,
        "signals": language_signals,
    }
    raw_payload = copy.deepcopy(payload)
    localize_payload(payload, language=output_languages[0], audience=audience, example_context=example_context)
    assign_announcement_priorities(payload)
    payload["content_review"] = review_release_notes(payload)
    localized_outputs = {output_languages[0]: "release-notes.html"}
    for extra_language in output_languages[1:]:
        extra_payload = copy.deepcopy(raw_payload)
        localize_payload(extra_payload, language=extra_language, audience=audience, example_context=example_context)
        assign_announcement_priorities(extra_payload)
        extra_payload["content_review"] = review_release_notes(extra_payload)
        extra_html_path = output_dir / f"release-notes.{extra_language}.html"
        extra_html_path.write_text(render_html(extra_payload), encoding="utf-8")
        localized_outputs[extra_language] = extra_html_path.name
    payload["localized_outputs"] = localized_outputs
    json_path = output_dir / "release-notes.json"
    evidence_path = output_dir / "change-evidence.json"
    html_path = output_dir / "release-notes.html"
    report_path = output_dir / "agent-report.md"
    artifacts = {
        "release-notes.html": str(html_path),
        "release-notes.json": str(json_path),
        "change-evidence.json": str(evidence_path),
        "agent-report.md": str(report_path),
    }
    if payload.get("browser_capture", {}).get("plan_path"):
        artifacts["screenshot-plan.json"] = str(payload["browser_capture"]["plan_path"])
    if payload.get("browser_capture", {}).get("capture_path"):
        artifacts["browser-capture.json"] = str(payload["browser_capture"]["capture_path"])
    for language, filename in localized_outputs.items():
        if filename != "release-notes.html":
            artifacts[f"release-notes.{language}.html"] = str(output_dir / filename)
    payload["agent_report"] = {"path": str(report_path)}
    write_json(json_path, payload)
    write_json(evidence_path, payload.get("change_evidence", {}))
    html_path.write_text(render_html(payload), encoding="utf-8")
    report_path.write_text(render_agent_report(payload, output_dir, artifacts), encoding="utf-8")
    print(html_path)


if __name__ == "__main__":
    main()
