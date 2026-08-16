from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from guidesync_agent.schemas import (
    GuideSyncRunRequest,
    ModelSettings,
    ProjectRunRequest,
    ProviderConfig,
    ProviderKind,
    ReportConfig,
    RepositoryInput,
    ScreenshotPolicy,
    TaskInterfaceAuthType,
)
from guidesync_agent.services import model_configuration
from guidesync_agent.services.model_configuration import (
    rehydrate_provider_credentials,
    with_run_provider_settings,
)
from guidesync_agent.services.reports.runs import task_interface_origins_match
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


def test_run_auth_is_injected_only_into_browser_runtime(tmp_path) -> None:
    request = GuideSyncRunRequest.model_construct(
        goal="Test authenticated screenshots",
        task_interface_url="https://example.com/product/",
        task_interface_auth_type=TaskInterfaceAuthType.COOKIE,
        task_interface_auth_secret=SecretStr("session=browser-secret"),
        has_task_interface_auth=True,
        report=ReportConfig(output_dir=tmp_path / "run"),
    )

    configured = with_run_provider_settings(ProviderConfig(), request)

    assert configured.browser is not None
    assert configured.browser.auth_type is TaskInterfaceAuthType.COOKIE
    assert configured.browser.auth_secret is not None
    assert configured.browser.auth_secret.get_secret_value() == "session=browser-secret"
    assert "browser-secret" not in configured.model_dump_json()
    assert "auth_secret" not in configured.browser.model_dump(mode="json")


def test_screenshot_policy_without_interface_url_is_nonblocking() -> None:
    with pytest.raises(ValidationError, match="screenshot_policy"):
        ProjectRunRequest.model_validate(
            {"goal": "Create a report.", "screenshot_policy": "required"}
        )
    run_request = GuideSyncRunRequest(
        goal="Create a report.",
        repositories=[RepositoryInput(name="repo", path=Path("."))],
        screenshot_policy=ScreenshotPolicy.REQUIRED,
    )

    assert run_request.task_interface_url is None


def test_project_ui_auth_can_only_be_inherited_by_the_same_origin() -> None:
    assert task_interface_origins_match(
        "https://console.example.com/report/1",
        "https://console.example.com/settings",
    )
    assert task_interface_origins_match(
        "https://console.example.com:443/report/1",
        "https://console.example.com/settings",
    )
    assert not task_interface_origins_match(
        "https://preview.example.com/report/1",
        "https://console.example.com/settings",
    )


def test_local_storage_auth_requires_a_string_map_and_stays_write_only() -> None:
    with pytest.raises(ValidationError, match="JSON object"):
        ProjectRunRequest.model_validate(
            {
                "goal": "Create a report.",
                "task_interface_auth_mode": "override",
                "task_interface_auth_type": "local_storage",
                "task_interface_auth_secret": "accessToken=secret",
            }
        )

    request = ProjectRunRequest.model_validate(
        {
            "goal": "Create a report.",
            "task_interface_auth_mode": "override",
            "task_interface_auth_type": "local_storage",
            "task_interface_auth_secret": '{"z":"one","accessToken":"secret"}',
        }
    )

    assert request.task_interface_auth_secret is not None
    assert request.task_interface_auth_secret.get_secret_value() == (
        '{"accessToken":"secret","z":"one"}'
    )
    assert "secret" not in request.model_dump_json()


def test_custom_api_key_names_are_resolved_by_settings(monkeypatch) -> None:
    monkeypatch.setenv("GUIDESYNC_TEST_PROVIDER_TOKEN", "test-secret")

    value = get_settings().credentials.api_key("GUIDESYNC_TEST_PROVIDER_TOKEN")

    assert value == "test-secret"


def test_saved_model_profile_credentials_are_rehydrated_without_changing_run_snapshot(
    monkeypatch,
) -> None:
    stored_profile = ModelSettings(
        id="model-hosted",
        name="Current profile name",
        provider=ProviderKind.PYDANTIC_AI,
        model="openai-responses:current-deployment",
        base_url="https://current.example.com/openai/v1/",
        api_key="stored-secret",
        has_api_key=True,
    )

    class ModelSettingsStoreStub:
        def list_profiles(self) -> list[ModelSettings]:
            return [stored_profile]

    monkeypatch.setattr(
        model_configuration,
        "create_model_settings_store",
        lambda: ModelSettingsStoreStub(),
    )
    persisted = ProviderConfig(
        provider=ProviderKind.PYDANTIC_AI,
        model="openai-responses:frozen-deployment",
        base_url="https://frozen.example.com/openai/v1/",
        timeout_seconds=321,
        metadata={"model_profile_id": stored_profile.id},
    )

    rehydrated = rehydrate_provider_credentials(persisted)

    assert rehydrated.api_key == "stored-secret"
    assert rehydrated.model == persisted.model
    assert rehydrated.base_url == persisted.base_url
    assert rehydrated.timeout_seconds == persisted.timeout_seconds


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
