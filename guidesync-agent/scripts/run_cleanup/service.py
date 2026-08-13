from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import cast

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from guidesync_agent.config import ArtifactStorageConfig
from guidesync_agent.schemas.project_cleanup import ProjectCleanupState
from guidesync_agent.services.project_cleanup import ProjectCleanupPlanError, S3CleanupClient

from .models import RunCleanupApplyResult, RunCleanupPlan, RunCleanupRequest, RunCleanupRun
from .storage import DatabaseRunCleanupStore


class RunCleanupService:
    def __init__(
        self,
        store: DatabaseRunCleanupStore,
        artifact_config: ArtifactStorageConfig,
        s3_client: S3CleanupClient | None = None,
    ) -> None:
        if not artifact_config.bucket:
            raise ProjectCleanupPlanError("GUIDESYNC_S3_BUCKET is required for run cleanup.")
        self.store = store
        self.artifact_config = artifact_config
        self.artifact_bucket = artifact_config.bucket
        self.s3_client = s3_client or boto3.client(
            "s3",
            endpoint_url=artifact_config.endpoint_url,
            region_name=artifact_config.region,
        )

    def preview(self, request: RunCleanupRequest) -> RunCleanupPlan:
        self._verify_protected_runs(request.protected_run_ids)
        runs = [self._run_preview(run_id) for run_id in request.target_run_ids]
        plan = RunCleanupPlan(
            artifact_bucket=self.artifact_bucket,
            artifact_endpoint_url=self.artifact_config.endpoint_url,
            artifact_prefix=self.artifact_config.prefix.strip("/"),
            target_run_ids=request.target_run_ids,
            protected_run_ids=request.protected_run_ids,
            runs=runs,
        )
        return plan.model_copy(update={"checksum": run_cleanup_plan_checksum(plan)})

    def apply(self, plan: RunCleanupPlan, confirmation: str) -> RunCleanupApplyResult:
        validate_run_plan_confirmation(plan, confirmation)
        self._validate_environment(plan)
        current = self.preview(
            RunCleanupRequest(
                target_run_ids=plan.target_run_ids,
                protected_run_ids=plan.protected_run_ids,
            )
        )
        if not current.safe_to_apply:
            raise ProjectCleanupPlanError(blocked_run_plan_message(current))
        if current.checksum != plan.checksum and not all_runs_absent(current):
            raise ProjectCleanupPlanError(
                "Run cleanup plan is stale. Generate and review a new preview before applying."
            )
        present_ids = [
            run.run_id for run in current.runs if run.state is ProjectCleanupState.PRESENT
        ]
        database_counts = self.store.delete_runs(present_ids) if present_ids else []
        deleted_keys, errors = self._delete_s3_keys(planned_s3_keys(plan.runs))
        return RunCleanupApplyResult(
            plan_checksum=plan.checksum,
            deleted_run_ids=present_ids,
            already_absent_run_ids=[
                run.run_id
                for run in current.runs
                if run.state is ProjectCleanupState.ALREADY_ABSENT
            ],
            database_counts=database_counts,
            deleted_s3_keys=deleted_keys,
            external_errors=errors,
        )

    def _run_preview(self, run_id: str) -> RunCleanupRun:
        run = self.store.preview_run(run_id)
        if run.state is ProjectCleanupState.ALREADY_ABSENT:
            return run
        return run.model_copy(update={"s3_keys": self._list_prefix(run_id)})

    def _verify_protected_runs(self, run_ids: Sequence[str]) -> None:
        missing = [
            run_id
            for run_id in run_ids
            if self.store.preview_run(run_id).state is ProjectCleanupState.ALREADY_ABSENT
        ]
        if missing:
            raise ProjectCleanupPlanError("Protected run rows are missing: " + ", ".join(missing))

    def _validate_environment(self, plan: RunCleanupPlan) -> None:
        current = (
            self.artifact_bucket,
            self.artifact_config.endpoint_url,
            self.artifact_config.prefix.strip("/"),
        )
        planned = (plan.artifact_bucket, plan.artifact_endpoint_url, plan.artifact_prefix)
        if current != planned:
            raise ProjectCleanupPlanError(
                "Cleanup storage configuration changed. Generate a new preview."
            )

    def _list_prefix(self, run_id: str) -> list[str]:
        prefix = f"{self.artifact_config.prefix.strip('/')}/{run_id}/"
        keys: list[str] = []
        continuation_token: str | None = None
        while True:
            kwargs: dict[str, object] = {
                "Bucket": self.artifact_bucket,
                "Prefix": prefix,
            }
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            response = self.s3_client.list_objects_v2(**kwargs)
            contents = cast(list[dict[str, object]], response.get("Contents", []))
            keys.extend(str(item["Key"]) for item in contents if "Key" in item)
            if not response.get("IsTruncated"):
                return sorted(set(keys))
            continuation_token = str(response["NextContinuationToken"])

    def _delete_s3_keys(self, keys: Sequence[str]) -> tuple[list[str], list[str]]:
        deleted: list[str] = []
        errors: list[str] = []
        for start in range(0, len(keys), 1000):
            batch = list(keys[start : start + 1000])
            try:
                response = self.s3_client.delete_objects(
                    Bucket=self.artifact_bucket,
                    Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
                )
            except (BotoCoreError, ClientError) as exc:
                errors.append(f"S3 batch delete failed: {exc}")
                continue
            response_errors = cast(list[dict[str, object]], response.get("Errors", []))
            failed = {str(item.get("Key")) for item in response_errors if item.get("Key")}
            deleted.extend(key for key in batch if key not in failed)
            errors.extend(
                f"S3 delete failed for {item.get('Key')}: {item.get('Message', 'unknown error')}"
                for item in response_errors
            )
        return deleted, errors


def run_cleanup_plan_checksum(plan: RunCleanupPlan) -> str:
    payload = plan.model_dump(mode="json", exclude={"checksum", "generated_at"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_run_plan_confirmation(plan: RunCleanupPlan, confirmation: str) -> None:
    if not plan.checksum or run_cleanup_plan_checksum(plan) != plan.checksum:
        raise ProjectCleanupPlanError("Run cleanup plan checksum is invalid.")
    if confirmation != plan.checksum:
        raise ProjectCleanupPlanError("Confirmation must exactly match the plan checksum.")
    if not plan.safe_to_apply:
        raise ProjectCleanupPlanError(blocked_run_plan_message(plan))


def blocked_run_plan_message(plan: RunCleanupPlan) -> str:
    blocked = [run.run_id for run in plan.runs if run.blocked]
    return "Run cleanup refused because protected or active data exists: " + ", ".join(blocked)


def all_runs_absent(plan: RunCleanupPlan) -> bool:
    return all(run.state is ProjectCleanupState.ALREADY_ABSENT for run in plan.runs)


def planned_s3_keys(runs: Sequence[RunCleanupRun]) -> list[str]:
    return sorted({key for run in runs for key in run.s3_keys})
