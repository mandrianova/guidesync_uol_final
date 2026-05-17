from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Locator, Page, sync_playwright


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
        file.write("\n")


def collect_page_evidence(page: Page) -> dict[str, Any]:
    visible_text = page.locator("body").inner_text(timeout=5000)
    html_lang = ""
    navigator_language = ""
    try:
        html_lang = page.locator("html").get_attribute("lang", timeout=1000) or ""
    except Exception:  # noqa: BLE001 - optional language signal
        html_lang = ""
    try:
        navigator_language = str(page.evaluate("navigator.language") or "")
    except Exception:  # noqa: BLE001 - optional language signal
        navigator_language = ""
    return {
        "url": page.url,
        "title": page.title(),
        "html_lang": html_lang,
        "navigator_language": navigator_language,
        "visible_text": visible_text[:12000],
    }


def resolve_locator(page: Page, step: dict[str, Any]) -> Locator:
    for selector in step.get("selectors", []):
        locator = page.locator(str(selector)).first
        try:
            locator.wait_for(timeout=1500)
            return locator
        except Exception:  # noqa: BLE001 - try next selector strategy
            continue
    if selector := step.get("selector"):
        return page.locator(str(selector))
    if test_id := step.get("test_id"):
        return page.get_by_test_id(str(test_id))
    if role := step.get("role"):
        name = step.get("name")
        return page.get_by_role(str(role), name=str(name) if name else None)
    if label := step.get("label"):
        return page.get_by_label(str(label))
    placeholders = step.get("placeholders") or ([step["placeholder"]] if step.get("placeholder") else [])
    for placeholder in placeholders:
        locator = page.get_by_placeholder(str(placeholder)).first
        try:
            locator.wait_for(timeout=1500)
            return locator
        except Exception:  # noqa: BLE001 - try next placeholder
            continue
    if target := step.get("target"):
        return page.get_by_text(str(target), exact=bool(step.get("exact", False)))
    raise ValueError("Step needs selector, test_id, role/name, label, placeholder or target.")


def validate_expected_text(page: Page, step: dict[str, Any]) -> dict[str, list[str]]:
    expected = step.get("expected_text") or []
    if isinstance(expected, str):
        expected = [expected]
    body_text = page.locator("body").inner_text(timeout=5000)
    matched = [text for text in expected if str(text) in body_text]
    missing = [text for text in expected if str(text) not in body_text]
    if missing and step.get("fail_on_missing_text", True):
        raise AssertionError(f"Missing expected text: {', '.join(missing)}")
    rejected = step.get("reject_text") or []
    if isinstance(rejected, str):
        rejected = [rejected]
    rejected_matches = [text for text in rejected if str(text) in body_text]
    if rejected_matches:
        raise AssertionError(f"Rejected page text found: {', '.join(rejected_matches)}")
    required = step.get("required_text") or []
    if isinstance(required, str):
        required = [required]
    required_missing = [text for text in required if str(text) not in body_text]
    if required_missing:
        raise AssertionError(f"Missing required page text: {', '.join(required_missing)}")
    required_any = step.get("required_any_text") or []
    if isinstance(required_any, str):
        required_any = [required_any]
    required_any_matches = [text for text in required_any if str(text) in body_text]
    if required_any and not required_any_matches:
        raise AssertionError(f"Missing any required page text: {', '.join(required_any)}")
    return {
        "matched_text": matched,
        "missing_text": missing,
        "rejected_text": rejected_matches,
        "missing_required_text": required_missing,
        "matched_required_any_text": required_any_matches,
    }


def decode_jwt_payload(token: str) -> dict[str, Any]:
    import base64

    parts = token.split(".")
    if len(parts) < 2:
        return {}

    payload = parts[1]
    padded = payload + ("=" * (-len(payload) % 4))
    try:
        return json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
    except Exception:  # noqa: BLE001 - best effort for optional auth bootstrap
        return {}


def build_auth0_bootstrap_script(token_env_name: str, token: str) -> str:
    token = token.removeprefix("Bearer ").strip()
    claims = decode_jwt_payload(token)
    client_id = "NlqrCrYKElirtRUiozeLDR9PHbVxyrRE"
    audience = "default"
    scope = claims.get("scope") if isinstance(claims.get("scope"), str) else "openid profile email"
    expires_at = int(claims.get("exp", 0)) if isinstance(claims.get("exp"), int) else int(datetime.now().timestamp()) + 3600
    expires_in = max(expires_at - int(datetime.now().timestamp()), 60)
    user = {
        "sub": claims.get("sub"),
        "email": claims.get("email"),
        "name": claims.get("name") or claims.get("nickname") or claims.get("sub"),
        "nickname": claims.get("nickname"),
        "picture": claims.get("picture"),
    }
    user = {key: value for key, value in user.items() if value}
    cache_key = f"@@auth0spajs@@::{client_id}::{audience}::{scope}"
    user_key = f"@@auth0spajs@@::{client_id}::@@user@@"
    cookie_name = f"auth0.{client_id}.is.authenticated"
    cache_entry = {
        "body": {
            "client_id": client_id,
            "access_token": token,
            "id_token": token,
            "scope": scope,
            "audience": audience,
            "expires_in": expires_in,
            "decodedToken": {
                "claims": claims,
                "user": user,
            },
        },
        "expiresAt": expires_at,
    }
    user_entry = {
        "id_token": token,
        "decodedToken": {
            "claims": claims,
            "user": user,
        },
    }

    return f"""
(() => {{
  const cacheKey = {json.dumps(cache_key)};
  const userKey = {json.dumps(user_key)};
  const cacheEntry = {json.dumps(cache_entry)};
  const userEntry = {json.dumps(user_entry)};
  window.localStorage.setItem(cacheKey, JSON.stringify(cacheEntry));
  window.localStorage.setItem(userKey, JSON.stringify(userEntry));
  document.cookie = {json.dumps(cookie_name)} + '=true; path=/; max-age=86400; SameSite=Lax';
  window.__GUIDESYNC_AUTH_BOOTSTRAP__ = {json.dumps({"mode": "auth0-localstorage", "token_env": token_env_name})};
}})();
"""


def perform_step(page: Page, step: dict[str, Any]) -> None:
    action = step.get("action")
    target = step.get("target")
    wait_before_ms = int(step.get("wait_before_ms", 0))
    if wait_before_ms:
        page.wait_for_timeout(wait_before_ms)

    if action == "navigate":
        page.goto(str(target), wait_until="domcontentloaded")
        return

    if action == "click":
        resolve_locator(page, step).click()
        return

    if action == "fill":
        if isinstance(target, str) and target.startswith(("http://", "https://", "file://")):
            page.goto(target, wait_until="domcontentloaded")
        value = step.get("value", "")
        resolve_locator(page, step).fill(str(value))
        return

    if action == "press":
        key = step.get("key")
        if not key:
            raise ValueError("press step requires key")
        resolve_locator(page, step).press(str(key))
        return

    if action == "wait_for_text":
        resolve_locator(page, step).wait_for()
        return

    if action == "wait_for_selector":
        selector = step.get("selector")
        if not selector:
            raise ValueError("wait_for_selector step requires selector")
        page.locator(str(selector)).wait_for()
        return

    if action == "wait_for_url":
        if not target:
            raise ValueError("wait_for_url step requires target")
        page.wait_for_url(str(target))
        return

    if action == "navigate_or_click":
        if isinstance(target, str) and target.startswith("/"):
            base_url = page.url.split("#", maxsplit=1)[0].rstrip("/")
            page.goto(f"{base_url}{target}", wait_until="domcontentloaded")
        else:
            resolve_locator(page, step).click()
        return

    if action == "screenshot":
        return

    if action == "scroll":
        delta_x = float(step.get("delta_x", 0))
        delta_y = float(step.get("delta_y", 900))
        page.mouse.wheel(delta_x, delta_y)
        page.wait_for_timeout(int(step.get("wait_ms", 500)))
        return

    raise ValueError(f"Unsupported action: {action}")


def capture_step_screenshot(page: Page, step: dict[str, Any], screenshot_path: Path) -> None:
    capture = step.get("capture") or {}
    if highlight_selector := capture.get("highlight_selector"):
        page.locator(str(highlight_selector)).evaluate_all(
            "(nodes) => nodes.forEach((node) => { node.style.outline = '3px solid #ff5a1f'; node.style.outlineOffset = '3px'; node.style.borderRadius = '8px'; })"
        )
    if capture.get("selector"):
        page.locator(str(capture["selector"])).screenshot(path=str(screenshot_path))
        return
    if clip := capture.get("clip"):
        page.screenshot(path=str(screenshot_path), clip={key: float(value) for key, value in clip.items()})
        return
    page.screenshot(path=str(screenshot_path), full_page=bool(capture.get("full_page", True)))


def maybe_wait_for_manual_auth(page: Page, enabled: bool) -> None:
    if not enabled:
        return

    print("Manual auth enabled.")
    print("Complete login in the opened browser, then press Enter here to continue.")
    input()
    page.wait_for_load_state("domcontentloaded")


def run_capture(
    plan_path: Path,
    screenshots_dir: Path,
    output_path: Path,
    *,
    headed: bool,
    manual_auth: bool,
    auth0_token_env: str | None,
    storage_state: Path | None,
    env_file: Path | None,
) -> None:
    plan = load_json(plan_path)
    plan_auth = plan.get("auth") or {}
    env_file = env_file or (Path(plan_auth["env_file"]) if plan_auth.get("env_file") else None)
    load_env_file(env_file)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "run_id": plan.get("run_id"),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "plan_path": str(plan_path),
        "screenshots_dir": str(screenshots_dir),
        "steps": [],
        "manual_auth": manual_auth,
    }

    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(headless=not headed)
        context_kwargs: dict[str, Any] = {"viewport": {"width": 1440, "height": 1000}}
        state_path = storage_state or (Path(plan_auth["state_path"]) if plan_auth.get("state_path") else None)
        if state_path:
            context_kwargs["storage_state"] = str(state_path)
            result["storage_state"] = str(state_path)
        context = browser.new_context(**context_kwargs)
        auth0_token_env = auth0_token_env or plan_auth.get("token_env")
        auth0_token = os.environ.get(auth0_token_env) if auth0_token_env else None
        if auth0_token_env:
            result["auth0_token_env"] = auth0_token_env
            result["auth0_bootstrap"] = "configured" if auth0_token else "missing-env"
        if env_file:
            result["env_file"] = str(env_file)
        if auth0_token:
            context.add_init_script(build_auth0_bootstrap_script(auth0_token_env or "", auth0_token))
        page = context.new_page()
        console_messages: list[dict[str, str]] = []
        page_errors: list[str] = []
        failed_requests: list[dict[str, str]] = []

        page.on(
            "console",
            lambda message: console_messages.append(
                {
                    "type": message.type,
                    "text": message.text[:1000],
                }
            ),
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)[:2000]))
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                {
                    "url": request.url,
                    "method": request.method,
                    "failure": str(request.failure or ""),
                }
            ),
        )

        try:
            for index, step in enumerate(plan.get("steps", []), start=1):
                step_result: dict[str, Any] = {
                    "id": step.get("id", f"step-{index:02d}"),
                    "action": step.get("action"),
                    "target": step.get("target"),
                    "status": "ok",
                }

                attempts = [step, *step.get("retries", [])]
                attempt_results: list[dict[str, Any]] = []
                for attempt_index, attempt in enumerate(attempts, start=1):
                    merged_step = {**step, **attempt}
                    merged_step["capture"] = {**(step.get("capture") or {}), **(attempt.get("capture") or {})}
                    try:
                        perform_step(page, merged_step)

                        if index == 1 and attempt_index == 1:
                            maybe_wait_for_manual_auth(page, manual_auth)

                        page.wait_for_load_state("domcontentloaded")
                        page.wait_for_timeout(int(merged_step.get("wait_after_ms", 1000)))
                        validation = validate_expected_text(page, merged_step)
                        screenshot_name = merged_step.get("screenshot") or f"{index:02d}-{step_result['id']}.png"
                        screenshot_path = screenshots_dir / screenshot_name
                        capture_step_screenshot(page, merged_step, screenshot_path)
                        step_result.update(
                            {
                                "status": "ok",
                                "action": merged_step.get("action"),
                                "target": merged_step.get("target"),
                                "validation": validation,
                                "expected": merged_step.get("expected"),
                                "screenshot": str(screenshot_path),
                                "evidence": collect_page_evidence(page),
                                "attempt": attempt_index,
                            }
                        )
                        break
                    except Exception as exc:  # noqa: BLE001 - try configured fallbacks before failing
                        attempt_result: dict[str, Any] = {
                            "attempt": attempt_index,
                            "action": merged_step.get("action"),
                            "target": merged_step.get("target"),
                            "error": str(exc),
                        }
                        try:
                            attempt_result["evidence"] = collect_page_evidence(page)
                        except Exception as evidence_exc:  # noqa: BLE001
                            attempt_result["evidence_error"] = str(evidence_exc)
                        attempt_results.append(attempt_result)
                else:
                    step_result["status"] = "failed"
                    step_result["error"] = attempt_results[-1]["error"] if attempt_results else "No capture attempts configured."
                    step_result["attempts"] = attempt_results
                    diagnostic_path = screenshots_dir / f"{index:02d}-{step_result['id']}-failed.png"
                    try:
                        page.screenshot(path=str(diagnostic_path), full_page=True)
                        step_result["diagnostic_screenshot"] = str(diagnostic_path)
                        step_result["evidence"] = collect_page_evidence(page)
                    except Exception as diagnostic_exc:  # noqa: BLE001
                        step_result["diagnostic_error"] = str(diagnostic_exc)

                result["steps"].append(step_result)
        finally:
            result["console_messages"] = console_messages[-50:]
            result["page_errors"] = page_errors[-20:]
            result["failed_requests"] = failed_requests[-50:]
            context.close()
            browser.close()

    write_json(output_path, result)
    print(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute a GuideSync screenshot plan with Playwright.")
    parser.add_argument("--plan", required=True, type=Path, help="Path to screenshot-plan.json.")
    parser.add_argument("--screenshots-dir", required=True, type=Path, help="Directory for captured screenshots.")
    parser.add_argument("--output", required=True, type=Path, help="Path to browser-capture.json.")
    parser.add_argument("--headed", action="store_true", help="Run browser headed for manual auth/debugging.")
    parser.add_argument("--manual-auth", action="store_true", help="Pause after first navigation for manual login.")
    parser.add_argument(
        "--auth0-token-env",
        help="Name of an environment variable containing a temporary Auth0 access token. The token is not written to output.",
    )
    parser.add_argument("--storage-state", type=Path, help="Playwright storage_state JSON for CI-safe authenticated runs.")
    parser.add_argument("--env-file", type=Path, help="Optional .env file with auth tokens. Values are not written to output.")
    args = parser.parse_args()

    run_capture(
        plan_path=args.plan,
        screenshots_dir=args.screenshots_dir,
        output_path=args.output,
        headed=args.headed,
        manual_auth=args.manual_auth,
        auth0_token_env=args.auth0_token_env,
        storage_state=args.storage_state,
        env_file=args.env_file,
    )


if __name__ == "__main__":
    main()
