from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from guidesync_agent.schemas import ModelRole, ModelSettings, ModelSettingsUpdate, ProviderKind
from guidesync_agent.storage import DatabaseModelSettingsStore, database_url

DEFAULT_GOOGLE_ORCHESTRATOR_MODEL = "google-cloud:gemini-3.1-pro-preview"
DEFAULT_GOOGLE_ANALYSIS_MODEL = "google-cloud:gemini-3.5-flash"
DEFAULT_GOOGLE_SCREENSHOT_MODEL = "google-cloud:gemini-3.5-flash"
DEFAULT_GOOGLE_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class GoogleModelProfileSeed:
    id: str
    name: str
    model: str
    roles: tuple[ModelRole, ...]


@dataclass(frozen=True)
class GoogleModelProfileSeedOptions:
    orchestrator_model: str = DEFAULT_GOOGLE_ORCHESTRATOR_MODEL
    analysis_model: str = DEFAULT_GOOGLE_ANALYSIS_MODEL
    screenshot_model: str = DEFAULT_GOOGLE_SCREENSHOT_MODEL
    timeout_seconds: int = DEFAULT_GOOGLE_TIMEOUT_SECONDS


def google_model_profile_seeds(
    options: GoogleModelProfileSeedOptions | None = None,
) -> tuple[GoogleModelProfileSeed, ...]:
    selected = options or GoogleModelProfileSeedOptions()
    return (
        GoogleModelProfileSeed(
            id="google-gemini-orchestrator",
            name="Google Gemini Orchestrator",
            model=selected.orchestrator_model,
            roles=(ModelRole.ORCHESTRATOR,),
        ),
        GoogleModelProfileSeed(
            id="google-gemini-analysis",
            name="Google Gemini Project Profile and Code Analysis",
            model=selected.analysis_model,
            roles=(
                ModelRole.PROJECT_PROFILE_FILE_READER,
                ModelRole.CODE_CHANGE_ANALYSIS,
            ),
        ),
        GoogleModelProfileSeed(
            id="google-gemini-screenshot-vision",
            name="Google Gemini Screenshot Vision",
            model=selected.screenshot_model,
            roles=(ModelRole.SCREENSHOT_VISION,),
        ),
    )


def seed_google_model_profiles(
    *,
    configured_database_url: str | None = None,
    options: GoogleModelProfileSeedOptions | None = None,
) -> list[ModelSettings]:
    selected = options or GoogleModelProfileSeedOptions()
    store = DatabaseModelSettingsStore(configured_database_url or database_url())
    saved_profiles: list[ModelSettings] = []
    for seed in google_model_profile_seeds(selected):
        saved_profiles.append(
            store.save_profile(
                ModelSettingsUpdate(
                    name=seed.name,
                    provider=ProviderKind.PYDANTIC_AI,
                    model=seed.model,
                    base_url=None,
                    timeout_seconds=selected.timeout_seconds,
                    roles=list(seed.roles),
                ),
                profile_id=seed.id,
                make_default=False,
            )
        )
    return saved_profiles


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Seed Google Gemini model profiles for GuideSync runtime roles. "
            "The existing local default profile is preserved as fallback."
        )
    )
    parser.add_argument("--database-url", help="Override GUIDESYNC_DATABASE_URL.")
    parser.add_argument(
        "--orchestrator-model",
        default=DEFAULT_GOOGLE_ORCHESTRATOR_MODEL,
        help="Model id for the orchestrator role.",
    )
    parser.add_argument(
        "--analysis-model",
        default=DEFAULT_GOOGLE_ANALYSIS_MODEL,
        help="Model id for project-profile and code-change roles.",
    )
    parser.add_argument(
        "--screenshot-model",
        default=DEFAULT_GOOGLE_SCREENSHOT_MODEL,
        help="Model id for the screenshot vision role.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_GOOGLE_TIMEOUT_SECONDS,
        help="Timeout assigned to each seeded profile.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    saved_profiles = seed_google_model_profiles(
        configured_database_url=args.database_url,
        options=GoogleModelProfileSeedOptions(
            orchestrator_model=args.orchestrator_model,
            analysis_model=args.analysis_model,
            screenshot_model=args.screenshot_model,
            timeout_seconds=args.timeout_seconds,
        ),
    )
    for profile in saved_profiles:
        roles = ", ".join(role.value for role in profile.roles) or "none"
        sys.stdout.write(f"{profile.id}: {profile.model} -> {roles}\n")


if __name__ == "__main__":
    main()
