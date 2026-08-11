from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from guidesync_agent.config import artifact_storage_config
from guidesync_agent.schemas.project_cleanup import (
    ProjectCleanupPlan,
    ProjectCleanupRequest,
)
from guidesync_agent.services.project_cleanup import (
    ProjectCleanupPlanError,
    ProjectCleanupService,
)
from guidesync_agent.settings import get_settings
from guidesync_agent.storage import database_url
from guidesync_agent.storage.database_project_cleanup import DatabaseProjectCleanupStore


def main() -> None:
    parser = argument_parser()
    args = parser.parse_args()
    try:
        validate_arguments(args)
        service = cleanup_service()
        if args.apply_plan:
            result = apply_saved_plan(service, args.apply_plan, args.confirm)
            print(json.dumps(result, indent=2))
            raise SystemExit(0 if result["complete"] else 1)
        plan = create_preview(service, args.target_project_id, args.protected_project_id)
        payload = plan_payload(plan)
        if args.plan_output:
            args.plan_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
    except (OSError, ProjectCleanupPlanError, ValidationError, ValueError) as exc:
        parser.exit(2, f"project cleanup refused: {exc}\n")


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or apply a guarded GuideSync project cleanup plan.",
    )
    parser.add_argument(
        "--target-project-id",
        action="append",
        default=[],
        help="Exact project id to delete. Repeat for multiple targets.",
    )
    parser.add_argument(
        "--protected-project-id",
        action="append",
        default=[],
        help="Exact report/evaluation project id that must remain. Repeat for the allowlist.",
    )
    parser.add_argument(
        "--plan-output",
        type=Path,
        help="Write the reviewed dry-run plan to this JSON file.",
    )
    parser.add_argument(
        "--apply-plan",
        type=Path,
        help="Apply a previously reviewed plan instead of creating a preview.",
    )
    parser.add_argument(
        "--confirm",
        help="Exact SHA-256 checksum printed in the reviewed plan.",
    )
    return parser


def validate_arguments(args: argparse.Namespace) -> None:
    preview_values = args.target_project_id or args.protected_project_id or args.plan_output
    if args.apply_plan and preview_values:
        raise ValueError("--apply-plan cannot be combined with preview arguments.")
    if not args.apply_plan and args.confirm:
        raise ValueError("--confirm is only valid with --apply-plan.")


def cleanup_service() -> ProjectCleanupService:
    settings = get_settings()
    return ProjectCleanupService(
        DatabaseProjectCleanupStore(database_url()),
        artifact_storage_config(),
        settings.paths.repository_cache_dir,
    )


def create_preview(
    service: ProjectCleanupService,
    target_project_ids: list[str],
    protected_project_ids: list[str],
) -> ProjectCleanupPlan:
    return service.preview(
        ProjectCleanupRequest(
            target_project_ids=target_project_ids,
            protected_project_ids=protected_project_ids,
        )
    )


def apply_saved_plan(
    service: ProjectCleanupService,
    path: Path,
    confirmation: str | None,
) -> dict[str, object]:
    if not confirmation:
        raise ProjectCleanupPlanError("--confirm is required with --apply-plan.")
    plan = ProjectCleanupPlan.model_validate_json(path.read_text(encoding="utf-8"))
    result = service.apply(plan, confirmation)
    payload = result.model_dump(mode="json")
    payload["complete"] = result.complete
    return payload


def plan_payload(plan: ProjectCleanupPlan) -> dict[str, object]:
    payload = plan.model_dump(mode="json")
    payload["safe_to_apply"] = plan.safe_to_apply
    return payload


if __name__ == "__main__":
    main()
