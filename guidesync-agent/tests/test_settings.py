from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from guidesync_agent.schemas import (
    GuideSyncRunRequest,
    ProjectRunRequest,
    ProviderConfig,
    ReportConfig,
    RepositoryInput,
    ScreenshotPolicy,
)
from guidesync_agent.services.model_configuration import with_run_provider_settings
from guidesync_agent.settings import BrowserToolSettings, get_settings
from guidesync_agent.tools.browser import browser_tool_config_from_provider
from guidesync_agent.tools.browser_support import find_browser_binary


def test_browser_environment_is_loaded_into_structured_settings(
    monkeypatch,
    tmp_path,
) -> None:
    screenshot_dir = tmp_path / "browser-captures"
    binary = tmp_path / "chromium"
    monkeypatch.setenv("GUIDESYNC_BROWSER_TOOL_ENABLED", "false")
    monkeypatch.setenv("GUIDESYNC_BROWSER_BASE_URL", "http://frontend.test")
    monkeypatch.setenv("GUIDESYNC_SCREENSHOT_DIR", str(screenshot_dir))
    monkeypatch.setenv("GUIDESYNC_BROWSER_TIMEOUT_MS", "23000")
    monkeypatch.setenv("GUIDESYNC_BROWSER_BINARY", str(binary))

    browser = get_settings().browser.tool_settings()

    assert browser == BrowserToolSettings(
        enabled=False,
        base_url="http://frontend.test",
        screenshot_dir=screenshot_dir,
        timeout_ms=23_000,
        binary=binary,
    )


def test_browser_provider_config_does_not_read_legacy_metadata(
    monkeypatch,
    tmp_path,
) -> None:
    configured_dir = tmp_path / "configured"
    monkeypatch.setenv("GUIDESYNC_BROWSER_BASE_URL", "http://settings.test")
    monkeypatch.setenv("GUIDESYNC_SCREENSHOT_DIR", str(configured_dir))
    provider = ProviderConfig(
        metadata={
            "browser_tool_enabled": False,
            "browser_base_url": "http://metadata.test",
            "screenshot_dir": str(tmp_path / "metadata"),
            "browser_timeout_ms": 1,
        }
    )

    browser = browser_tool_config_from_provider(provider)

    assert browser.enabled is True
    assert browser.base_url == "http://settings.test"
    assert browser.screenshot_dir == configured_dir
    assert browser.timeout_ms == 15_000


def test_run_screenshot_directory_is_a_structured_browser_override(tmp_path) -> None:
    provider = ProviderConfig(
        browser=BrowserToolSettings(
            base_url="http://frontend.test",
            screenshot_dir=tmp_path / "default",
            timeout_ms=9_000,
        )
    )
    request = GuideSyncRunRequest.model_construct(
        goal="Test settings",
        report=ReportConfig(output_dir=tmp_path / "run"),
    )

    configured = with_run_provider_settings(provider, request)

    assert configured.browser is not None
    assert configured.browser.base_url == "http://frontend.test"
    assert configured.browser.timeout_ms == 9_000
    assert configured.browser.screenshot_dir == tmp_path / "run" / "screenshots"
    assert "screenshot_dir" not in configured.metadata


def test_run_interface_url_becomes_browser_origin_when_profile_has_none(tmp_path) -> None:
    provider = ProviderConfig(
        browser=BrowserToolSettings(
            screenshot_dir=tmp_path / "default",
        )
    )
    request = GuideSyncRunRequest.model_construct(
        goal="Test settings",
        task_interface_url="https://example.com/product/",
        report=ReportConfig(output_dir=tmp_path / "run"),
    )

    configured = with_run_provider_settings(provider, request)

    assert configured.browser is not None
    assert configured.browser.base_url == "https://example.com/product/"


def test_run_interface_url_overrides_profile_browser_origin(tmp_path) -> None:
    provider = ProviderConfig(
        browser=BrowserToolSettings(
            base_url="https://stale.example.com/",
            screenshot_dir=tmp_path / "default",
        )
    )
    request = GuideSyncRunRequest.model_construct(
        goal="Test settings",
        task_interface_url="https://current.example.com/product/",
        report=ReportConfig(output_dir=tmp_path / "run"),
    )

    configured = with_run_provider_settings(provider, request)

    assert configured.browser is not None
    assert configured.browser.base_url == "https://current.example.com/product/"


def test_run_auth_cookie_is_injected_only_into_browser_runtime(tmp_path) -> None:
    request = GuideSyncRunRequest.model_construct(
        goal="Test authenticated screenshots",
        task_interface_url="https://example.com/product/",
        task_interface_auth_cookie=SecretStr("session=browser-secret"),
        has_task_interface_auth_cookie=True,
        report=ReportConfig(output_dir=tmp_path / "run"),
    )

    configured = with_run_provider_settings(ProviderConfig(), request)

    assert configured.browser is not None
    assert configured.browser.auth_cookie is not None
    assert configured.browser.auth_cookie.get_secret_value() == "session=browser-secret"
    assert "browser-secret" not in configured.model_dump_json()
    assert "auth_cookie" not in configured.browser.model_dump(mode="json")


def test_screenshot_policy_without_interface_url_is_nonblocking() -> None:
    project_request = ProjectRunRequest(
        goal="Create a report.",
        screenshot_policy=ScreenshotPolicy.REQUIRED,
    )
    run_request = GuideSyncRunRequest(
        goal="Create a report.",
        repositories=[RepositoryInput(name="repo", path=Path("."))],
        screenshot_policy=ScreenshotPolicy.REQUIRED,
    )

    assert project_request.task_interface_url is None
    assert run_request.task_interface_url is None


def test_custom_api_key_names_are_resolved_by_settings(monkeypatch) -> None:
    monkeypatch.setenv("GUIDESYNC_TEST_PROVIDER_TOKEN", "test-secret")

    value = get_settings().credentials.api_key("GUIDESYNC_TEST_PROVIDER_TOKEN")

    assert value == "test-secret"


def test_browser_binary_discovery_uses_structured_settings(monkeypatch, tmp_path) -> None:
    binary = tmp_path / "chromium"
    binary.touch()
    monkeypatch.setenv("GUIDESYNC_BROWSER_BINARY", str(binary))

    assert find_browser_binary() == str(binary)


def test_production_environment_access_is_confined_to_settings_module() -> None:
    project_root = Path(__file__).resolve().parents[1]
    settings_path = project_root / "src/guidesync_agent/settings.py"
    source_paths = [
        *sorted((project_root / "src/guidesync_agent").rglob("*.py")),
        *sorted((project_root / "migrations").rglob("*.py")),
    ]
    forbidden = ("os.environ", "os.getenv", "from os import getenv")
    violations = [
        str(path.relative_to(project_root))
        for path in source_paths
        if path != settings_path
        and any(pattern in path.read_text(encoding="utf-8") for pattern in forbidden)
    ]

    assert violations == []
