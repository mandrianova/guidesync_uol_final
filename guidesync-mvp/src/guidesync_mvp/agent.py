from __future__ import annotations

import argparse
import copy
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

SUPPORTED_GUIDE_LANGUAGES = {"en", "ru"}

USER_TITLE_PATTERNS = (
    (("domain",), {"en": "Custom domains", "ru": "Пользовательские домены"}),
    (
        ("resource", "mention"),
        {"en": "File and resource mentions in chat", "ru": "Упоминания файлов и ресурсов в чате"},
    ),
    (("slash", "command"), {"en": "Slash commands in chat", "ru": "Slash-команды в чате"}),
    (
        ("workspace", "permission"),
        {"en": "Workspace access controls", "ru": "Управление доступом к рабочей области"},
    ),
    (("permission", "control"), {"en": "Access controls", "ru": "Управление доступом"}),
    (("skill",), {"en": "Agent skills", "ru": "Навыки агента"}),
)

AREA_LABELS = {
    "account menu": {"en": "account menu", "ru": "меню аккаунта"},
    "billing": {"en": "billing and plan", "ru": "оплата и тариф"},
    "chat": {"en": "chat", "ru": "чат"},
    "common layout": {"en": "main interface", "ru": "основной интерфейс"},
    "domains": {"en": "domains", "ru": "домены"},
    "homepage": {"en": "home page", "ru": "главная страница"},
    "markdown": {"en": "messages and posts", "ru": "сообщения и публикации"},
    "settings": {"en": "settings", "ru": "настройки"},
    "solution": {"en": "project", "ru": "проект"},
    "ui": {"en": "interface", "ru": "интерфейс"},
}

UI_LANGUAGE_KEYWORDS = {
    "en": (
        "home",
        "settings",
        "save",
        "cancel",
        "continue",
        "domain",
        "domains",
        "chat",
        "new chat",
        "upload",
        "workspace",
        "profile",
    ),
    "ru": (
        "главная",
        "настройки",
        "сохранить",
        "отмена",
        "продолжить",
        "домен",
        "домены",
        "чат",
        "загрузить",
        "рабочая область",
        "профиль",
    ),
}

TEXT = {
    "en": {
        "default_title": "What's new in the product",
        "subtitle": "Here are the newest product improvements worth trying: what they help with, where to find them, and one practical way to use each one.",
        "period": "Period",
        "features": "Features",
        "generated": "Prepared",
        "stat_features": "updates ready to explore",
        "stat_captured": "confirmed in the live UI",
        "stat_uncertain": "items need a final copy check",
        "footer": "Draft release notes for a user mailing. Review names, access rules, and screenshots before publishing.",
        "where": "Where to find it",
        "related": "Related areas",
        "how": "How to try it",
        "examples": "Ways to use it",
        "screenshot": "Interface screenshot from the automated walkthrough",
        "capture_failed": "The automated UI walkthrough did not finish for this item",
        "badge": "User update",
        "example": "Example",
        "expected": "What users should see:",
        "empty_title": "No user-facing changes found",
        "empty_body": "The agent did not find changes that are ready to describe in a user mailing for this period. Try a wider period or add route overrides for the relevant screens.",
        "home_page": "home page",
        "unknown_location": "the relevant product area",
        "ordinary_user": "regular user",
        "why": "Why it matters",
    },
    "ru": {
        "default_title": "Что нового в продукте",
        "subtitle": "Собрали новые улучшения, которые стоит попробовать: зачем они нужны, где их найти и как использовать в обычной работе.",
        "period": "Период",
        "features": "Функции",
        "generated": "Собрано",
        "stat_features": "обновлений, которые можно попробовать",
        "stat_captured": "подтверждено в живом интерфейсе",
        "stat_uncertain": "пунктов требуют финальной проверки текста",
        "footer": "Черновик релизной рассылки для пользователей. Перед публикацией проверьте названия, права доступа и скриншоты.",
        "where": "Где искать",
        "related": "Связанные разделы",
        "how": "Как попробовать",
        "examples": "Примеры использования",
        "screenshot": "Скриншот интерфейса из автоматического прохода",
        "capture_failed": "Автоматический проход UI для этого пункта не завершился",
        "badge": "Для пользователей",
        "example": "Пример",
        "expected": "Что должен увидеть пользователь:",
        "empty_title": "Пользовательских изменений не найдено",
        "empty_body": "За выбранный период агент не нашёл изменений, которые готовы для описания в пользовательской рассылке. Попробуйте расширить период или добавить route overrides для нужных экранов.",
        "home_page": "главная страница",
        "unknown_location": "нужный раздел продукта",
        "ordinary_user": "обычный пользователь",
        "why": "Зачем это нужно",
    },
}

FEATURE_COPY = {
    "domains": {
        "en": {
            "title": "Custom domains",
            "location": "Domains",
            "summary": "You can now connect your own domain to an Ardor workspace, so shared apps and artifacts can live at a familiar branded URL.",
            "benefit": "This makes published work easier to share with teammates, clients, or stakeholders because the link can use your own domain instead of a generated product URL.",
            "steps": [
                "Open Ardor and go to the Domains page for your workspace or project.",
                "Choose Add domain and enter the domain you want to connect.",
                "Copy the DNS records shown by Ardor into your domain provider.",
                "Return to Ardor to check the setup status before sharing the new URL.",
            ],
            "examples": [
                {
                    "title": "Publish under your own brand",
                    "scenario": "Add a company-owned domain before sharing an app or artifact with people outside your workspace.",
                    "expected_result": "Recipients open a clean, recognizable URL that belongs to your team.",
                },
                {
                    "title": "Check DNS setup in one place",
                    "scenario": "Use the Domains page to see which DNS records still need attention.",
                    "expected_result": "You know whether the domain is ready to use or what has to be fixed first.",
                },
            ],
        },
        "ru": {
            "title": "Пользовательские домены",
            "location": "Домены",
            "summary": "Теперь к рабочей области Ardor можно подключить собственный домен, чтобы опубликованные приложения и артефакты открывались по понятному branded URL.",
            "benefit": "Так результат проще показывать коллегам, клиентам или стейкхолдерам: ссылка выглядит как адрес вашей команды, а не как технический URL продукта.",
            "steps": [
                "Откройте Ardor и перейдите на страницу доменов для рабочей области или проекта.",
                "Нажмите Add domain и укажите домен, который хотите подключить.",
                "Скопируйте DNS-записи из Ardor в настройки вашего доменного провайдера.",
                "Вернитесь в Ardor и проверьте статус настройки перед тем, как делиться ссылкой.",
            ],
            "examples": [
                {
                    "title": "Публикация под своим брендом",
                    "scenario": "Добавьте домен компании перед тем, как отправлять приложение или артефакт людям вне рабочей области.",
                    "expected_result": "Получатели открывают понятную ссылку, которая принадлежит вашей команде.",
                },
                {
                    "title": "Проверка DNS-настроек",
                    "scenario": "Откройте страницу доменов, чтобы увидеть, какие DNS-записи ещё требуют внимания.",
                    "expected_result": "Понятно, готов ли домен к использованию или что нужно исправить.",
                },
            ],
        },
    },
    "resource_mentions": {
        "en": {
            "title": "Mention files and resources in chat",
            "location": "Chat",
            "summary": "Chat can now reference project files and resources directly, so you can give Ardor clearer context without describing everything manually.",
            "benefit": "This helps the assistant work from the exact material you mean and reduces back-and-forth when a task depends on a specific file, artifact, or resource.",
            "steps": [
                "Open a chat in Ardor.",
                "Start typing your request and use the resource mention control when you need to point to a file or artifact.",
                "Select the relevant resource from the picker.",
                "Send the message with the resource attached as context.",
            ],
            "examples": [
                {
                    "title": "Ask about a specific file",
                    "scenario": "Mention a file in chat and ask Ardor to explain, update, or use it in the current task.",
                    "expected_result": "The assistant uses the selected file as context instead of guessing which file you meant.",
                },
                {
                    "title": "Keep complex requests focused",
                    "scenario": "Reference the relevant artifact before asking for changes.",
                    "expected_result": "The conversation stays tied to the right source material.",
                },
            ],
        },
        "ru": {
            "title": "Упоминания файлов и ресурсов в чате",
            "location": "Чат",
            "summary": "В чате теперь можно ссылаться на файлы и ресурсы проекта, чтобы давать Ardor точный контекст без длинных объяснений.",
            "benefit": "Ассистенту проще работать с нужным материалом, а вам не нужно каждый раз описывать, какой файл или артефакт имеется в виду.",
            "steps": [
                "Откройте чат в Ardor.",
                "Начните писать запрос и используйте выбор ресурса, когда нужно сослаться на файл или артефакт.",
                "Выберите нужный ресурс из списка.",
                "Отправьте сообщение: выбранный ресурс будет использоваться как контекст.",
            ],
            "examples": [
                {
                    "title": "Спросить про конкретный файл",
                    "scenario": "Упомяните файл в чате и попросите Ardor объяснить, обновить или использовать его в задаче.",
                    "expected_result": "Ассистент работает с выбранным файлом, а не угадывает, что вы имели в виду.",
                },
                {
                    "title": "Сфокусировать сложный запрос",
                    "scenario": "Сошлитесь на нужный артефакт перед тем, как просить изменения.",
                    "expected_result": "Диалог остаётся привязанным к правильному материалу.",
                },
            ],
        },
    },
    "slash_commands": {
        "en": {
            "title": "Slash commands in chat",
            "location": "Chat",
            "summary": "Chat now supports slash commands, giving you a faster way to start common actions without searching through menus.",
            "benefit": "Slash commands make repeat tasks easier to discover and quicker to launch from the place where you already describe your work.",
            "steps": [
                "Open a chat in Ardor.",
                "Type / in the message box.",
                "Choose the command that matches what you want to do.",
                "Fill in any details the command asks for and send it.",
            ],
            "examples": [
                {
                    "title": "Start a common action faster",
                    "scenario": "Type / and pick the action you need instead of looking for it elsewhere in the product.",
                    "expected_result": "You can begin the workflow directly from chat.",
                },
                {
                    "title": "Discover available chat actions",
                    "scenario": "Open the slash command list to see what Ardor can help with from the composer.",
                    "expected_result": "The available actions are visible at the moment you need them.",
                },
            ],
        },
        "ru": {
            "title": "Slash-команды в чате",
            "location": "Чат",
            "summary": "В чате появились slash-команды: быстрый способ запускать частые действия без поиска по меню.",
            "benefit": "Повторяющиеся задачи проще найти и быстрее запустить прямо из места, где вы уже формулируете запрос.",
            "steps": [
                "Откройте чат в Ardor.",
                "Введите / в поле сообщения.",
                "Выберите команду, которая подходит под вашу задачу.",
                "Заполните дополнительные детали, если они нужны, и отправьте команду.",
            ],
            "examples": [
                {
                    "title": "Быстрее начать частое действие",
                    "scenario": "Введите / и выберите нужное действие вместо того, чтобы искать его в других разделах продукта.",
                    "expected_result": "Рабочий сценарий запускается прямо из чата.",
                },
                {
                    "title": "Посмотреть доступные действия",
                    "scenario": "Откройте список slash-команд, чтобы увидеть, что Ardor умеет делать из composer.",
                    "expected_result": "Доступные действия видны именно в момент, когда они нужны.",
                },
            ],
        },
    },
    "workspace_permissions": {
        "en": {
            "title": "Workspace access controls",
            "location": "Workspace settings",
            "summary": "Workspace owners get clearer controls for who can access workspace capabilities and billing-related areas.",
            "benefit": "Teams can keep sensitive workspace actions limited to the right people while regular users stay focused on their day-to-day work.",
            "steps": [
                "Open your account menu and go to workspace or settings.",
                "Find the access, permissions, or billing area for the workspace.",
                "Review who can use the protected workspace actions.",
                "Adjust access before inviting teammates into sensitive workflows.",
            ],
            "examples": [
                {
                    "title": "Prepare a workspace for a team",
                    "scenario": "Review permissions before inviting new teammates.",
                    "expected_result": "Only the right roles can reach sensitive workspace actions.",
                },
                {
                    "title": "Keep billing actions protected",
                    "scenario": "Check that billing and plan controls are available only to the people responsible for them.",
                    "expected_result": "Users see the controls that match their role.",
                },
            ],
        },
        "ru": {
            "title": "Управление доступом к рабочей области",
            "location": "Настройки рабочей области",
            "summary": "Владельцам рабочей области стали понятнее доступны настройки того, кто может пользоваться важными возможностями и разделами, связанными с оплатой.",
            "benefit": "Команда может ограничить чувствительные действия нужными ролями, а обычные пользователи будут видеть только то, что относится к их работе.",
            "steps": [
                "Откройте меню аккаунта и перейдите в рабочую область или настройки.",
                "Найдите раздел доступа, прав или оплаты для рабочей области.",
                "Проверьте, кто может пользоваться защищёнными действиями.",
                "Настройте доступ перед тем, как приглашать команду в чувствительные сценарии.",
            ],
            "examples": [
                {
                    "title": "Подготовить рабочую область для команды",
                    "scenario": "Проверьте права перед приглашением новых участников.",
                    "expected_result": "К чувствительным действиям имеют доступ только нужные роли.",
                },
                {
                    "title": "Защитить оплату и тариф",
                    "scenario": "Убедитесь, что управление оплатой доступно только ответственным людям.",
                    "expected_result": "Пользователи видят действия, которые соответствуют их роли.",
                },
            ],
        },
    },
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


def language_text(language: str, key: str) -> str:
    return TEXT.get(language, TEXT["en"]).get(key, TEXT["en"][key])


def normalize_language(raw_language: str | None) -> str | None:
    if not raw_language:
        return None
    language = str(raw_language).strip().lower().replace("_", "-").split("-", maxsplit=1)[0]
    return language if language in SUPPORTED_GUIDE_LANGUAGES else None


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
    for raw_languages in (
        output.get("languages"),
        output.get("locales"),
        task.get("languages"),
        task.get("locales"),
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
    for raw_language in (
        output.get("language"),
        output.get("locale"),
        task.get("language"),
        task.get("locale"),
        ui.get("language"),
        ui.get("locale"),
    ):
        language = normalize_language(raw_language)
        if language:
            return language
    return None


def infer_language_from_text(text: str) -> str | None:
    normalized = text.lower()
    if re.search(r"[а-яё]", normalized):
        return "ru"
    scores = {
        language: sum(1 for keyword in keywords if keyword in normalized)
        for language, keywords in UI_LANGUAGE_KEYWORDS.items()
    }
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

    return "en", signals or [{"source": "default", "value": "en", "language": "en"}]


def user_facing_title(raw_title: str, features: list[str], routes: list[str], language: str) -> str:
    text = " ".join([raw_title, *features, *routes]).lower()
    for needles, titles in USER_TITLE_PATTERNS:
        if all(needle in text for needle in needles):
            return titles.get(language, titles["en"])
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


def display_area(area: str, language: str) -> str:
    label = AREA_LABELS.get(area)
    if label:
        return label.get(language, label["en"])
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
    copies = FEATURE_COPY.get(key) or {}
    return copies.get(language) or copies.get("en")


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
    steps = []
    if language == "ru":
        if routes:
            steps.append(f"Откройте продукт и перейдите в раздел “{display_location(title, routes, features, language)}”.")
        elif features:
            steps.append(f"Откройте раздел “{display_location(title, routes, features, language)}”.")
        else:
            steps.append("Откройте продукт и найдите новый или изменённый раздел в основном меню.")
        steps.append(f"Найдите на экране элементы, связанные с “{title}”.")
        steps.append("Используйте видимые кнопки, поля и подсказки интерфейса, чтобы выполнить действие.")
        steps.append("Посмотрите на результат на экране и продолжайте обычный рабочий сценарий.")
        return steps

    if routes:
        steps.append(f"Open the product and go to “{display_location(title, routes, features, language)}”.")
    elif features:
        steps.append(f"Open “{display_location(title, routes, features, language)}”.")
    else:
        steps.append("Open the product and look for the new or updated area in the main navigation.")
    steps.append(f"Find the controls related to “{title}”.")
    steps.append("Use the visible controls in the interface to complete the task.")
    steps.append("Review the on-screen result and continue your normal workflow.")
    return steps


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
    if language == "ru":
        return [
            {
                "title": "Быстро найти новую возможность",
                "scenario": f"{context_prefix}Пользователь открывает “{location}” и находит “{title}” по видимым названиям, кнопкам или подсказкам.",
                "expected_result": "Понятно, где находится новая возможность и с какого действия начать.",
            },
            {
                "title": "Применить в обычной задаче",
                "scenario": f"{readable_audience.capitalize()} выполняет привычный сценарий в этом разделе и использует “{title}” там, где раньше приходилось искать обходной путь.",
                "expected_result": "Пользователь видит изменение прямо в интерфейсе и понимает, как оно помогает в работе.",
            },
        ]
    return [
        {
            "title": "Find the new capability",
            "scenario": f"{context_prefix}A user opens “{location}” and finds “{title}” through the visible headings, buttons, or helper text.",
            "expected_result": "The user understands where the new capability lives and where to start.",
        },
        {
            "title": "Use it in a real workflow",
            "scenario": f"A {readable_audience} completes a familiar task in this area and uses “{title}” where they previously needed a workaround.",
            "expected_result": "The user sees the change in the interface and understands how it helps their work.",
        },
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
        "score": user_facing_score(change),
    }


def summarise_change(title: str, routes: list[str], features: list[str], language: str) -> str:
    copy_block = feature_copy(title, routes, features, language)
    if copy_block and copy_block.get("summary"):
        return str(copy_block["summary"])
    if language == "ru":
        if routes:
            return f"В этом релизе появилась возможность “{title}”. Ищите её в разделе “{display_location(title, routes, features, language)}”."
        if features:
            return f"В этом релизе обновилась возможность “{title}” в разделе “{display_area(features[0], language)}”."
        return f"В продукте появилось изменение “{title}”; его точное место в интерфейсе нужно уточнить."
    if routes:
        return f"“{title}” is now available from “{display_location(title, routes, features, language)}”, so you can try it in your normal workflow."
    if features:
        return f"“{title}” is now available in “{display_location(title, routes, features, language)}”, so it is easier to use where you already work."
    return f"This release includes “{title}”; the exact place in the interface still needs confirmation."


def feature_benefit(title: str, routes: list[str], features: list[str], language: str) -> str:
    copy_block = feature_copy(title, routes, features, language)
    if copy_block and copy_block.get("benefit"):
        return str(copy_block["benefit"])
    if language == "ru":
        return f"Это изменение должно сократить лишние шаги и сделать сценарий “{title}” понятнее прямо в интерфейсе."
    return f"This should reduce extra steps and make “{title}” easier to discover in the product."


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
      --bg: #fbfaf7;
      --ink: #171b1f;
      --muted: #68727b;
      --line: #dde2e4;
      --panel: #ffffff;
      --soft: #eef5f2;
      --accent: #ff5a1f;
      --accent-2: #126b7f;
      --accent-3: #6f4bb8;
      --good: #1f7a53;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .shell { max-width: 1180px; margin: 0 auto; padding: 34px 22px 76px; }
    .hero { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(320px, .95fr); gap: 34px; align-items: center; min-height: 520px; padding: 38px 0 42px; border-bottom: 1px solid var(--line); }
    .eyebrow { margin: 0 0 18px; color: var(--accent-2); font-size: 13px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; }
    h1 { margin: 0; font-size: 62px; line-height: .96; letter-spacing: 0; max-width: 820px; }
    .subtitle { margin: 22px 0 0; color: #4b565f; max-width: 720px; line-height: 1.58; font-size: 19px; }
    .hero-actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 28px; }
    .button { display: inline-flex; align-items: center; border: 1px solid var(--ink); color: #fff; background: var(--ink); padding: 12px 16px; font-weight: 800; text-decoration: none; }
    .button.secondary { color: var(--ink); background: transparent; border-color: var(--line); }
    .hero-panel { background: var(--panel); border: 1px solid var(--line); padding: 24px; box-shadow: 0 24px 70px rgba(23, 27, 31, .08); }
    .hero-panel h2 { margin: 0; font-size: 22px; }
    .takeaways { display: grid; gap: 14px; margin-top: 18px; }
    .takeaway { display: grid; grid-template-columns: 24px minmax(0, 1fr); gap: 14px; align-items: start; }
    .takeaway-num { width: 24px; height: 24px; display: grid; place-items: center; color: var(--accent); background: #fff3ed; border: 1px solid #ffd1bd; border-radius: 999px; font-size: 12px; line-height: 1; font-weight: 900; }
    .takeaway strong { display: block; margin-bottom: 3px; }
    .takeaway span { display: block; color: var(--muted); line-height: 1.45; font-size: 14px; }
    .section { padding: 42px 0 0; }
    .section-head { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
    .section h2 { margin: 0; font-size: 34px; letter-spacing: 0; }
    .section p.lede { margin: 8px 0 0; color: var(--muted); max-width: 700px; line-height: 1.55; }
    .spotlight { display: grid; grid-template-columns: minmax(320px, .82fr) minmax(0, 1.18fr); gap: 22px; background: #ffffff; border: 1px solid var(--line); }
    .spotlight-copy { padding: 26px; }
    .badge { display: inline-block; color: #fff; background: var(--accent-2); padding: 6px 10px; font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: .05em; }
    .spotlight h3 { margin: 18px 0 0; font-size: 34px; line-height: 1.04; }
    .spotlight p { color: var(--muted); line-height: 1.58; margin: 12px 0 0; }
    .try-list { margin: 18px 0 0; padding-left: 20px; }
    .try-list li { margin: 9px 0; line-height: 1.45; }
    .spotlight-media { background: #f1f4f5; border-left: 1px solid var(--line); padding: 18px; display: flex; align-items: center; }
    .spotlight-media img { display: block; width: 100%; max-height: 620px; object-fit: contain; border: 1px solid var(--line); background: #fff; }
    .media-caption { color: var(--muted); font-size: 13px; margin-top: 10px; line-height: 1.4; }
    .group-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
    .update-card { background: var(--panel); border: 1px solid var(--line); padding: 18px; min-height: 100%; }
    .update-card h3 { margin: 10px 0 0; font-size: 22px; line-height: 1.12; }
    .update-card p { color: var(--muted); line-height: 1.52; margin: 10px 0 0; }
    .card-shot { display: block; width: 100%; max-height: 220px; object-fit: contain; margin-top: 14px; border: 1px solid var(--line); background: #f7f9f9; }
    details { margin-top: 14px; border-top: 1px solid var(--line); padding-top: 12px; }
    summary { cursor: pointer; color: var(--ink); font-weight: 800; }
    .mini-label { color: var(--accent-3); font-size: 12px; font-weight: 900; text-transform: uppercase; letter-spacing: .06em; }
    .example-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .example { border-top: 1px solid var(--line); padding-top: 12px; }
    .example strong { display: block; margin-bottom: 5px; }
    .example span { display: block; color: var(--muted); line-height: 1.42; font-size: 13px; }
    .cta { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 20px; align-items: center; margin-top: 42px; background: var(--ink); color: #fff; padding: 28px; }
    .cta h2 { margin: 0; font-size: 30px; }
    .cta p { margin: 8px 0 0; color: #dce3e7; line-height: 1.5; max-width: 720px; }
    .cta .button { background: var(--accent); border-color: var(--accent); }
    footer { margin-top: 24px; color: var(--muted); font-size: 13px; line-height: 1.5; }
    @media (max-width: 820px) {
      .hero, .spotlight, .group-grid, .example-grid, .cta { grid-template-columns: 1fr; }
      .spotlight-media { border-left: 0; border-top: 1px solid var(--line); }
      h1 { font-size: 42px; }
    }
    """


def title_for_language(payload: dict[str, Any], language: str) -> str:
    title = str(payload.get("title") or "").strip()
    project = payload.get("project") or {}
    project_name = project.get("name") or "the product"
    if language == "en" and re.search(r"[а-яё]", title.lower()):
        return f"What's new in {project_name}"
    if language == "ru" and title in {"What's new in the product", "What's new"}:
        return f"Что нового в {project_name}"
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
    project = (payload.get("project") or {}).get("name") or "Ardor"
    feature_text = " ".join(feature.get("title", "") for feature in payload.get("features", [])).lower()
    if language == "ru":
        if "domain" in feature_text or "домен" in feature_text:
            return f"Новые способы быстрее работать и делиться результатами в {project}"
        return f"Что стало удобнее в {project}"
    if "domain" in feature_text:
        return f"New ways to work faster and share with confidence in {project}"
    return f"Here is what is easier to do in {project}"


def announcement_subtitle(payload: dict[str, Any], language: str) -> str:
    if language == "ru":
        return "В этом релизе стало проще давать ассистенту контекст, запускать действия из чата, управлять доступом и публиковать результат под своим доменом."
    return "This release makes it easier to give Ardor context, start actions from chat, control workspace access, and publish work under your own domain."


def announcement_eyebrow(payload: dict[str, Any], language: str) -> str:
    period = payload.get("period") or ""
    if language == "ru":
        return f"Product update • {period}"
    return f"Product update • {period}"


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


def spotlight_feature(features: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not features:
        return None
    for feature in features:
        if (feature.get("announcement_priority") or {}).get("role") == "spotlight":
            return feature
    return sorted(features, key=feature_sort_key)[0]


def feature_theme(feature: dict[str, Any], language: str) -> str:
    key = feature_copy_key(str(feature.get("title", "")), feature.get("routes", []), feature.get("areas", []))
    if language == "ru":
        return {
            "resource_mentions": "Больше контекста",
            "slash_commands": "Быстрее из чата",
            "domains": "Профессиональная публикация",
            "workspace_permissions": "Контроль доступа",
        }.get(key or "", "Улучшение")
    return {
        "resource_mentions": "More context",
        "slash_commands": "Faster from chat",
        "domains": "Professional sharing",
        "workspace_permissions": "Access control",
    }.get(key or "", "Improvement")


def render_takeaways(features: list[dict[str, Any]], language: str) -> str:
    title = "Why try this release" if language != "ru" else "Почему стоит попробовать"
    rows = []
    for index, item in enumerate(takeaways(features, language), start=1):
        rows.append(
            f"""
            <div class="takeaway">
              <span class="takeaway-num">{index}</span>
              <div><strong>{html.escape(item["title"])}</strong><span>{html.escape(item["body"])}</span></div>
            </div>
"""
        )
    return f"""
          <div class="hero-panel">
            <h2>{html.escape(title)}</h2>
            <div class="takeaways">{''.join(rows)}</div>
          </div>
"""


def render_spotlight(feature: dict[str, Any], language: str) -> str:
    examples = feature.get("examples") or []
    primary_example = examples[0] if examples else {}
    steps = "".join(f"<li>{html.escape(step)}</li>" for step in (feature.get("steps") or [])[:4])
    capture = feature.get("capture") or {}
    screenshot = capture.get("screenshot")
    media = ""
    if screenshot:
        media = f"""
          <div>
            <img src="{html.escape(screenshot)}" alt="{html.escape(feature.get("title", ""))}" />
            <p class="media-caption">{html.escape("Look for the live controls in Ardor, then follow the visible setup hints." if language != "ru" else "Найдите эти элементы в Ardor и следуйте подсказкам интерфейса.")}</p>
          </div>
"""
    else:
        media = f"""
          <div>
            <p class="media-caption">{html.escape("Screenshot capture is still missing for this update, but the workflow is described below." if language != "ru" else "Скриншот для этого обновления пока не снят, но сценарий описан ниже.")}</p>
          </div>
"""
    return f"""
      <section class="section" id="spotlight">
        <div class="section-head">
          <div>
            <h2>{html.escape("Spotlight" if language != "ru" else "Главное обновление")}</h2>
            <p class="lede">{html.escape("Start here if you want one useful thing to try first." if language != "ru" else "Начните отсюда, если хотите попробовать самое заметное изменение.")}</p>
          </div>
        </div>
        <article class="spotlight">
          <div class="spotlight-copy">
            <span class="badge">{html.escape(feature_theme(feature, language))}</span>
            <h3>{html.escape(feature.get("title", ""))}</h3>
            <p>{html.escape(feature.get("summary", ""))}</p>
            <p><strong>{html.escape(language_text(language, "why"))}:</strong> {html.escape(feature.get("benefit", ""))}</p>
            <ol class="try-list">{steps}</ol>
            <div class="example">
              <strong>{html.escape(primary_example.get("title", ""))}</strong>
              <span>{html.escape(primary_example.get("scenario", ""))}</span>
            </div>
          </div>
          <div class="spotlight-media">{media}</div>
        </article>
      </section>
"""


def render_update_card(feature: dict[str, Any], language: str) -> str:
    examples = feature.get("examples") or []
    steps = feature.get("steps") or []
    first_step = steps[0] if steps else ""
    step_items = "".join(f"<li>{html.escape(step)}</li>" for step in steps)
    example_items = "".join(render_example(example, language) for example in examples)
    capture = feature.get("capture") or {}
    screenshot = capture.get("screenshot")
    screenshot_html = (
        f'<img class="card-shot" src="{html.escape(screenshot)}" alt="{html.escape(feature.get("title", ""))}" />'
        if screenshot
        else ""
    )
    details_label = "Full steps and examples" if language != "ru" else "Все шаги и примеры"
    return f"""
        <article class="update-card">
          <span class="mini-label">{html.escape(feature_theme(feature, language))}</span>
          <h3>{html.escape(feature.get("title", ""))}</h3>
          <p>{html.escape(feature.get("summary", ""))}</p>
          <p><strong>{html.escape(language_text(language, "how"))}:</strong> {html.escape(first_step)}</p>
          {screenshot_html}
          <details>
            <summary>{html.escape(details_label)}</summary>
            <ol class="try-list">{step_items}</ol>
            <div class="example-grid">{example_items}</div>
          </details>
        </article>
"""


def render_supporting_updates(features: list[dict[str, Any]], spotlight: dict[str, Any] | None, language: str) -> str:
    supporting = [feature for feature in features if feature is not spotlight]
    if not supporting:
        return ""
    cards = "".join(render_update_card(feature, language) for feature in supporting)
    title = "Also in this release" if language != "ru" else "Ещё в этом релизе"
    lede = (
        "A few smaller changes make everyday work smoother across chat, workspace setup, and sharing."
        if language != "ru"
        else "Несколько дополнительных улучшений делают повседневную работу удобнее в чате, настройках и публикации."
    )
    return f"""
      <section class="section">
        <div class="section-head">
          <div>
            <h2>{html.escape(title)}</h2>
            <p class="lede">{html.escape(lede)}</p>
          </div>
        </div>
        <div class="group-grid">{cards}</div>
      </section>
"""


def render_cta(features: list[dict[str, Any]], language: str) -> str:
    if language == "ru":
        title = "Попробуйте прямо сейчас"
        body = "Откройте чат и введите /, добавьте ресурс в запрос или перейдите в Domains, чтобы подключить собственный домен."
        action = "Начать с чата"
    else:
        title = "Try the new flow now"
        body = "Open chat and type /, attach a resource to your prompt, or visit Domains to connect a branded URL."
        action = "Start in chat"
    return f"""
      <section class="cta">
        <div>
          <h2>{html.escape(title)}</h2>
          <p>{html.escape(body)}</p>
        </div>
        <a class="button" href="#spotlight">{html.escape(action)}</a>
      </section>
"""


def render_html(payload: dict[str, Any]) -> str:
    language = normalize_language(payload.get("language")) or "en"
    features = sorted(
        [feature for feature in payload["features"] if is_user_visible_feature(feature)],
        key=feature_sort_key,
    )
    spotlight = spotlight_feature(features)
    spotlight_html = render_spotlight(spotlight, language) if spotlight else render_empty_state(language)
    supporting_html = render_supporting_updates(features, spotlight, language)
    cta_html = render_cta(features, language) if features else ""
    return f"""<!doctype html>
<html lang="{html.escape(language)}">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(payload["title"])}</title>
    <style>{css()}</style>
  </head>
  <body>
    <main class="shell">
      <header class="hero">
        <div>
          <p class="eyebrow">{html.escape(announcement_eyebrow(payload, language))}</p>
          <h1>{html.escape(announcement_headline(payload, language))}</h1>
          <p class="subtitle">{html.escape(announcement_subtitle(payload, language))}</p>
          <div class="hero-actions">
            <a class="button" href="#spotlight">{html.escape("See what to try" if language != "ru" else "Что попробовать")}</a>
            <a class="button secondary" href="#all-updates">{html.escape("Browse all updates" if language != "ru" else "Все обновления")}</a>
          </div>
        </div>
        {render_takeaways(features, language) if features else ""}
      </header>
      {spotlight_html}
      <div id="all-updates">{supporting_html}</div>
      {cta_html}
      <footer>
        {html.escape("Generated as a user-facing product announcement from recent Ardor changes." if language != "ru" else "Сгенерировано как пользовательский анонс последних изменений продукта.")}
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


def render_feature(feature: dict[str, Any], index: int, language: str) -> str:
    title = str(feature.get("title", ""))
    routes = "".join(
        f'<span class="chip">{html.escape(display_location(title, [route], feature.get("areas", []), language))}</span>'
        for route in feature["routes"]
    )
    areas = "".join(f'<span class="chip">{html.escape(display_area(area, language))}</span>' for area in feature["areas"])
    location_blocks = ""
    if routes:
        location_blocks += f"<h3>{html.escape(language_text(language, 'where'))}</h3><div class=\"chips\">{routes}</div>"
    if areas:
        location_blocks += f"<h3>{html.escape(language_text(language, 'related'))}</h3><div class=\"chips\">{areas}</div>"
    steps = "".join(f"<li>{html.escape(step)}</li>" for step in feature["steps"])
    examples = "".join(render_example(example, language) for example in feature.get("examples", []))
    screenshot_html = ""
    capture = feature.get("capture") or {}
    if capture.get("screenshot"):
        screenshot_html = f"""
        <div class="shot">
          <p>{html.escape(language_text(language, "screenshot"))}</p>
          <img src="{html.escape(capture["screenshot"])}" alt="{html.escape(feature["title"])}" />
        </div>
"""
    elif capture.get("status") == "failed":
        screenshot_html = f"""
        <div class="shot">
          <p>{html.escape(language_text(language, "capture_failed"))}: {html.escape(capture.get("error", "unknown error"))}</p>
        </div>
"""
    return f"""
      <article class="feature">
        <div class="feature-head">
          <div>
            <h2>{index}. {html.escape(feature["title"])}</h2>
            <p>{html.escape(feature["summary"])}</p>
            <p><strong>{html.escape(language_text(language, "why"))}:</strong> {html.escape(feature.get("benefit") or feature_benefit(feature["title"], feature.get("routes", []), feature.get("areas", []), language))}</p>
          </div>
          <span class="badge">{html.escape(language_text(language, "badge"))}</span>
        </div>
        <div class="feature-body">
          <section>
            <h3>{html.escape(language_text(language, "how"))}</h3>
            <ol>{steps}</ol>
          </section>
          <aside class="side">
            {location_blocks}
          </aside>
        </div>
        <div class="examples">
          <h3>{html.escape(language_text(language, "examples"))}</h3>
          <div class="example-grid">{examples}</div>
        </div>
        {screenshot_html}
      </article>
"""


def render_example(example: dict[str, str], language: str) -> str:
    return f"""
            <div class="example">
              <strong>{html.escape(example.get("title", language_text(language, "example")))}</strong>
              <span>{html.escape(example.get("scenario", ""))}</span>
              <span><b>{html.escape(language_text(language, "expected"))}</b> {html.escape(example.get("expected_result", ""))}</span>
            </div>
"""


def render_empty_state(language: str) -> str:
    return f"""
      <article class="feature">
        <div class="feature-head">
          <div>
            <h2>{html.escape(language_text(language, "empty_title"))}</h2>
            <p>{html.escape(language_text(language, "empty_body"))}</p>
          </div>
        </div>
      </article>
"""


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
    if features:
        for index, feature in enumerate(sorted(features, key=feature_sort_key), start=1):
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
        if finding.get("severity") in {"needs-fix", "warning"}:
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
    features = [
        build_feature(change, audience=audience, example_context=example_context, language=language)
        for change in candidates[:max_features]
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
    placeholders = ui.get("chat_input_placeholders") or [
        "Ask Ardor to create an AI scheduling assistant...",
        "Describe an app or agent you want to create",
    ]
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
                "role": "combobox",
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
                "role": "combobox",
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
    explicit_languages = configured_languages(config)
    initial_language = explicit_languages[0] if explicit_languages else "en"
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
    output_languages = explicit_languages or [detected_language]
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
    html_path = output_dir / "release-notes.html"
    report_path = output_dir / "agent-report.md"
    artifacts = {
        "release-notes.html": str(html_path),
        "release-notes.json": str(json_path),
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
    html_path.write_text(render_html(payload), encoding="utf-8")
    report_path.write_text(render_agent_report(payload, output_dir, artifacts), encoding="utf-8")
    print(html_path)


if __name__ == "__main__":
    main()
