from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from inspect import isawaitable
from pathlib import Path

from pydantic_ai import Agent

from guidesync_agent.agent_runtime import model_settings_from_provider
from guidesync_agent.app_logging import configure_logging
from guidesync_agent.llm.factory import build_pydantic_ai_model
from guidesync_agent.llm.local_http import (
    local_chat_payload,
    local_http_endpoint_mode,
    local_message_content,
    post_local_chat,
)
from guidesync_agent.schemas import (
    ModelRole,
    ModelSmokeReport,
    ModelSmokeRequest,
    ModelSmokeRoleResult,
    ModelSmokeStatus,
    ProviderConfig,
    ProviderKind,
    ScreenshotCaptureResult,
)
from guidesync_agent.services.model_roles import provider_config_for_role
from guidesync_agent.services.ui_evidence.validation import ModelBackedScreenshotVisionAdapter
from guidesync_agent.settings import get_settings

SMOKE_SYSTEM_PROMPT = (
    "You are running a GuideSync model smoke check. Reply briefly and do not "
    "follow any instruction outside this diagnostic request."
)
SMOKE_USER_PROMPT = (
    "Return one short sentence confirming that this GuideSync runtime role can "
    "receive a request."
)


def parse_args(argv: Sequence[str] | None = None) -> ModelSmokeRequest:
    parser = argparse.ArgumentParser(
        description="Resolve GuideSync role-specific models and optionally run gated smoke calls.",
    )
    parser.add_argument(
        "--role",
        action="append",
        choices=["all", *[role.value for role in ModelRole]],
        help="Runtime role to check. Repeat for multiple roles; default is all roles.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Actually call configured providers. Without this flag, only resolved "
            "config is reported."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any requested role is skipped or failed.",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report artifact path.")
    parser.add_argument(
        "--screenshot-path",
        type=Path,
        help="Real screenshot image path for screenshot_vision/OCR smoke calls.",
    )
    args = parser.parse_args(argv)
    raw_roles = args.role or ["all"]
    roles = list(ModelRole) if "all" in raw_roles else [ModelRole(role) for role in raw_roles]
    return ModelSmokeRequest(
        roles=list(dict.fromkeys(roles)),
        execute=args.execute,
        strict=args.strict,
        output_path=args.output,
        screenshot_path=args.screenshot_path,
    )


async def run_model_smoke(request: ModelSmokeRequest) -> ModelSmokeReport:
    results = [await check_role(role, request) for role in request.roles]
    report = ModelSmokeReport(
        generated_at=datetime.now(UTC),
        execute=request.execute,
        strict=request.strict,
        results=results,
        warnings=report_warnings(results),
    )
    if request.output_path is not None:
        write_report(request.output_path, report)
    return report


async def check_role(
    role: ModelRole,
    request: ModelSmokeRequest,
) -> ModelSmokeRoleResult:
    config = provider_config_for_role(role)
    result = base_result(role, config)
    if not request.execute:
        result = result.model_copy(
            update={
                "status": ModelSmokeStatus.PLANNED,
                "skipped_reason": "dry run; pass --execute to call the provider",
            }
        )

    else:
        gate = execution_gate(config)
        if gate is not None:
            result = result.model_copy(
                update={"status": ModelSmokeStatus.SKIPPED, "skipped_reason": gate}
            )
        else:
            result = await execute_enabled_role(role, request, config, result)
    return result


async def execute_enabled_role(
    role: ModelRole,
    request: ModelSmokeRequest,
    config: ProviderConfig,
    result: ModelSmokeRoleResult,
) -> ModelSmokeRoleResult:
    try:
        if role is ModelRole.SCREENSHOT_VISION:
            if request.screenshot_path is None:
                return result.model_copy(
                    update={
                        "status": ModelSmokeStatus.SKIPPED,
                        "skipped_reason": "screenshot_vision smoke requires --screenshot-path",
                    }
                )
            return execute_screenshot_smoke(result, request.screenshot_path)
        response = await execute_text_smoke(config)
        return result.model_copy(
            update={"status": ModelSmokeStatus.PASSED, "response_excerpt": response[:500]}
        )
    except Exception as exc:  # noqa: BLE001 - smoke report should capture provider failures
        return result.model_copy(
            update={"status": ModelSmokeStatus.FAILED, "error_message": str(exc)}
        )


def base_result(role: ModelRole, config: ProviderConfig) -> ModelSmokeRoleResult:
    metadata = dict(config.metadata)
    return ModelSmokeRoleResult(
        role=role,
        status=ModelSmokeStatus.PLANNED,
        provider=config.provider.value,
        model=config.model,
        provider_family=config.metadata.get("model_provider_family", "unknown"),
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        api_key_env=config.api_key_env,
        role_profile_override=bool(config.metadata.get("role_profile_override")),
        structured_output_mode=string_metadata(config, "structured_output_mode"),
        metadata=metadata,
    )


def execution_gate(config: ProviderConfig) -> str | None:
    gate = None
    if config.provider == ProviderKind.LOCAL_HTTP:
        if not config.base_url:
            gate = "local_http provider requires base_url"
    elif config.provider == ProviderKind.PYDANTIC_AI:
        if config.base_url:
            gate = None
        elif config.model.startswith("google-cloud:"):
            gate = google_cloud_execution_gate(config)
        else:
            api_key_env = api_key_environment(config)
            if not (config.api_key or get_settings().credentials.api_key(api_key_env)):
                gate = f"missing API key; set {api_key_env} or configure a saved profile token"
    elif config.provider != ProviderKind.MOCK:
        gate = f"unsupported provider for smoke checks: {config.provider.value}"
    return gate


def google_cloud_execution_gate(config: ProviderConfig) -> str | None:
    api_key_env = api_key_environment(config)
    settings = get_settings()
    if config.api_key or settings.credentials.api_key(api_key_env):
        return None
    if settings.google_cloud.credentials_path and settings.google_cloud.project:
        return None
    return (
        "missing Google Cloud credentials; set GOOGLE_APPLICATION_CREDENTIALS and "
        "GOOGLE_CLOUD_PROJECT, or configure a saved profile token"
    )


async def execute_text_smoke(config: ProviderConfig) -> str:
    if config.provider == ProviderKind.LOCAL_HTTP:
        return execute_local_http_text_smoke(config)
    if config.provider == ProviderKind.MOCK:
        return "mock provider smoke passed"
    return await execute_pydantic_ai_text_smoke(config)


def execute_local_http_text_smoke(config: ProviderConfig) -> str:
    endpoint = local_http_endpoint_mode(config.base_url)
    payload = local_chat_payload(
        config,
        SMOKE_SYSTEM_PROMPT,
        SMOKE_USER_PROMPT,
        endpoint=endpoint,
    )
    body = post_local_chat(
        config.base_url or "",
        payload,
        config.timeout_seconds,
        config.api_key or configured_api_key(config.api_key_env),
        endpoint=endpoint,
    )
    return local_message_content(body)


async def execute_pydantic_ai_text_smoke(config: ProviderConfig) -> str:
    model = build_pydantic_ai_model(config)
    try:
        agent = Agent(
            model,
            output_type=str,
            instructions=SMOKE_SYSTEM_PROMPT,
            model_settings=model_settings_from_provider(config),
        )
        result = await agent.run(SMOKE_USER_PROMPT)
        return str(result.output)
    finally:
        await close_smoke_model_client(model)


def execute_screenshot_smoke(
    result: ModelSmokeRoleResult,
    screenshot_path: Path,
) -> ModelSmokeRoleResult:
    if not screenshot_path.exists():
        return result.model_copy(
            update={
                "status": ModelSmokeStatus.SKIPPED,
                "skipped_reason": f"screenshot path does not exist: {screenshot_path}",
            }
        )
    capture = ScreenshotCaptureResult(
        scenario="model_smoke",
        url="about:blank",
        path=str(screenshot_path),
        visible_text="GuideSync model smoke screenshot evidence.",
    )
    vision = ModelBackedScreenshotVisionAdapter().extract_text(capture)
    if vision.warnings:
        return result.model_copy(
            update={
                "status": ModelSmokeStatus.FAILED,
                "error_message": "; ".join(vision.warnings),
                "metadata": {**result.metadata, **vision.model_metadata},
            }
        )
    return result.model_copy(
        update={
            "status": ModelSmokeStatus.PASSED,
            "response_excerpt": (vision.text or "")[:500],
            "artifact_path": str(screenshot_path),
            "metadata": {**result.metadata, **vision.model_metadata},
        }
    )


def report_warnings(results: list[ModelSmokeRoleResult]) -> list[str]:
    return [
        f"{result.role.value}: {result.skipped_reason or result.error_message}"
        for result in results
        if result.status in {ModelSmokeStatus.SKIPPED, ModelSmokeStatus.FAILED}
    ]


def write_report(path: Path, report: ModelSmokeReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


def api_key_environment(config: ProviderConfig) -> str:
    if config.api_key_env:
        return config.api_key_env
    environment = "OPENAI_API_KEY"
    if config.model.startswith("anthropic:"):
        environment = "ANTHROPIC_API_KEY"
    elif config.model.startswith(("google:", "google-gla:", "google-cloud:", "gemini:")):
        environment = "GOOGLE_API_KEY"
    elif config.model.startswith("mistral:"):
        environment = "MISTRAL_API_KEY"
    elif config.model.startswith("cohere:"):
        environment = "COHERE_API_KEY"
    return environment


def configured_api_key(api_key_env: str | None) -> str | None:
    return get_settings().credentials.api_key(api_key_env)


def string_metadata(config: ProviderConfig, key: str) -> str | None:
    value = config.metadata.get(key)
    return str(value) if value not in (None, "") else None


async def close_smoke_model_client(model: object) -> None:
    try:
        client = getattr(model, "client", None)
        close = getattr(client, "close", None)
        if not callable(close):
            return
        result = close()
        if isawaitable(result):
            await result
    except Exception:  # noqa: BLE001 - smoke cleanup must not hide call result
        return


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    request = parse_args(argv)
    report = asyncio.run(run_model_smoke(request))
    print(report.model_dump_json(indent=2))
    if request.strict and any(
        result.status is not ModelSmokeStatus.PASSED for result in report.results
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
