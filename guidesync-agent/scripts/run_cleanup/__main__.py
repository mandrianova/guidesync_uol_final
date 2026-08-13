from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from guidesync_agent.config import artifact_storage_config
from guidesync_agent.services.project_cleanup import ProjectCleanupPlanError
from guidesync_agent.storage import database_url

from .models import RunCleanupPlan, RunCleanupRequest
from .service import RunCleanupService
from .storage import DatabaseRunCleanupStore


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
        plan = service.preview(
            RunCleanupRequest(
                target_run_ids=args.target_run_id,
                protected_run_ids=args.protected_run_id,
            )
        )
        payload = plan_payload(plan)
        if args.plan_output:
            args.plan_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
    except (OSError, ProjectCleanupPlanError, ValidationError, ValueError) as exc:
        parser.exit(2, f"run cleanup refused: {exc}\n")


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or apply a guarded GuideSync legacy-run cleanup plan.",
    )
    parser.add_argument("--target-run-id", action="append", default=[])
    parser.add_argument("--protected-run-id", action="append", default=[])
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--apply-plan", type=Path)
    parser.add_argument("--confirm")
    return parser


def validate_arguments(args: argparse.Namespace) -> None:
    preview_values = args.target_run_id or args.protected_run_id or args.plan_output
    if args.apply_plan and preview_values:
        raise ValueError("--apply-plan cannot be combined with preview arguments.")
    if not args.apply_plan and args.confirm:
        raise ValueError("--confirm is only valid with --apply-plan.")


def cleanup_service() -> RunCleanupService:
    return RunCleanupService(
        DatabaseRunCleanupStore(database_url()),
        artifact_storage_config(),
    )


def apply_saved_plan(
    service: RunCleanupService,
    path: Path,
    confirmation: str | None,
) -> dict[str, object]:
    if not confirmation:
        raise ProjectCleanupPlanError("--confirm is required with --apply-plan.")
    plan = RunCleanupPlan.model_validate_json(path.read_text(encoding="utf-8"))
    result = service.apply(plan, confirmation)
    payload = result.model_dump(mode="json")
    payload["complete"] = result.complete
    return payload


def plan_payload(plan: RunCleanupPlan) -> dict[str, object]:
    payload = plan.model_dump(mode="json")
    payload["safe_to_apply"] = plan.safe_to_apply
    return payload


if __name__ == "__main__":
    main()
