from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from guidesync_agent.config import ArtifactStorageConfig
from guidesync_agent.schemas.project_cleanup import (
    ProjectCleanupApplyResult,
    ProjectCleanupPlan,
    ProjectCleanupProject,
    ProjectCleanupRepositoryCache,
    ProjectCleanupRequest,
    ProjectCleanupState,
)
from guidesync_agent.storage.database_project_cleanup import DatabaseProjectCleanupStore


class S3CleanupClient(Protocol):
    def list_objects_v2(self, **kwargs: object) -> dict[str, object]: ...

    def delete_objects(self, **kwargs: object) -> dict[str, object]: ...


class ProjectCleanupPlanError(RuntimeError):
    pass


class ProjectCleanupService:
    def __init__(
        self,
        store: DatabaseProjectCleanupStore,
        artifact_config: ArtifactStorageConfig,
        repository_cache_root: Path,
        s3_client: S3CleanupClient | None = None,
    ) -> None:
        if not artifact_config.bucket:
            raise ProjectCleanupPlanError("GUIDESYNC_S3_BUCKET is required for project cleanup.")
        self.store = store
        self.artifact_config = artifact_config
        self.artifact_bucket = artifact_config.bucket
        self.repository_cache_root = repository_cache_root
        self.s3_client = s3_client or boto3.client(
            "s3",
            endpoint_url=artifact_config.endpoint_url,
            region_name=artifact_config.region,
        )

    def preview(self, request: ProjectCleanupRequest) -> ProjectCleanupPlan:
        self._verify_protected_projects(request.protected_project_ids)
        target_ids = set(request.target_project_ids)
        projects = [
            self._project_preview(project_id, target_ids)
            for project_id in request.target_project_ids
        ]
        plan = ProjectCleanupPlan(
            artifact_bucket=self.artifact_bucket,
            artifact_endpoint_url=self.artifact_config.endpoint_url,
            artifact_prefix=self.artifact_config.prefix.strip("/"),
            repository_cache_root=str(self.repository_cache_root.resolve()),
            target_project_ids=request.target_project_ids,
            protected_project_ids=request.protected_project_ids,
            projects=projects,
        )
        return plan.model_copy(update={"checksum": cleanup_plan_checksum(plan)})

    def apply(self, plan: ProjectCleanupPlan, confirmation: str) -> ProjectCleanupApplyResult:
        validate_plan_confirmation(plan, confirmation)
        self._validate_plan_environment(plan)
        request = ProjectCleanupRequest(
            target_project_ids=plan.target_project_ids,
            protected_project_ids=plan.protected_project_ids,
        )
        current = self.preview(request)
        if not current.safe_to_apply:
            raise ProjectCleanupPlanError(blocked_plan_message(current))
        if current.checksum != plan.checksum and not all_projects_absent(current):
            raise ProjectCleanupPlanError(
                "Cleanup plan is stale. Generate and review a new preview before applying."
            )

        present_ids = [
            project.project_id
            for project in current.projects
            if project.state is ProjectCleanupState.PRESENT
        ]
        database_counts = self.store.delete_projects(present_ids) if present_ids else []
        deleted_keys, external_errors = self._delete_s3_keys(planned_s3_keys(plan.projects))
        deleted_paths, cache_errors = self._delete_repository_caches(plan)
        external_errors.extend(cache_errors)
        return ProjectCleanupApplyResult(
            plan_checksum=plan.checksum,
            deleted_project_ids=present_ids,
            already_absent_project_ids=[
                project.project_id
                for project in current.projects
                if project.state is ProjectCleanupState.ALREADY_ABSENT
            ],
            database_counts=database_counts,
            deleted_s3_keys=deleted_keys,
            deleted_repository_cache_paths=deleted_paths,
            external_errors=external_errors,
        )

    def _validate_plan_environment(self, plan: ProjectCleanupPlan) -> None:
        current = (
            self.artifact_bucket,
            self.artifact_config.endpoint_url,
            self.artifact_config.prefix.strip("/"),
            str(self.repository_cache_root.resolve()),
        )
        planned = (
            plan.artifact_bucket,
            plan.artifact_endpoint_url,
            plan.artifact_prefix,
            plan.repository_cache_root,
        )
        if current != planned:
            raise ProjectCleanupPlanError(
                "Cleanup storage configuration changed. Generate a new preview."
            )

    def _verify_protected_projects(self, project_ids: Sequence[str]) -> None:
        missing = [
            project_id
            for project_id in project_ids
            if self.store.preview_project(project_id).state is ProjectCleanupState.ALREADY_ABSENT
        ]
        if missing:
            raise ProjectCleanupPlanError(
                "Protected project rows are missing: " + ", ".join(missing)
            )

    def _project_preview(
        self,
        project_id: str,
        target_project_ids: set[str],
    ) -> ProjectCleanupProject:
        project = self.store.preview_project(project_id)
        if project.state is ProjectCleanupState.ALREADY_ABSENT:
            return project
        caches = [
            cache.model_copy(
                update={
                    "deletable": not (set(cache.shared_project_ids) - target_project_ids)
                    and self._safe_cache_path(cache.path)
                }
            )
            for cache in project.repository_caches
        ]
        return project.model_copy(
            update={
                "repository_caches": caches,
                "s3_keys": self._list_run_keys(project.run_ids),
            }
        )

    def _list_run_keys(self, run_ids: Sequence[str]) -> list[str]:
        keys: list[str] = []
        prefix = self.artifact_config.prefix.strip("/")
        for run_id in run_ids:
            keys.extend(self._list_prefix(f"{prefix}/{run_id}/"))
        return sorted(set(keys))

    def _list_prefix(self, prefix: str) -> list[str]:
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
                break
            continuation_token = str(response["NextContinuationToken"])
        return keys

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
            failed = {
                str(item.get("Key"))
                for item in response_errors
                if isinstance(item, dict) and item.get("Key")
            }
            deleted.extend(key for key in batch if key not in failed)
            errors.extend(
                f"S3 delete failed for {item.get('Key')}: {item.get('Message', 'unknown error')}"
                for item in response_errors
                if isinstance(item, dict)
            )
        return deleted, errors

    def _delete_repository_caches(
        self,
        plan: ProjectCleanupPlan,
    ) -> tuple[list[str], list[str]]:
        deleted: list[str] = []
        errors: list[str] = []
        for cache in planned_repository_caches(plan.projects):
            users = self.store.cache_path_users(cache.path, plan.target_project_ids)
            if users:
                continue
            if not cache.deletable or not self._safe_cache_path(cache.path):
                errors.append(f"Repository cache path is not safe to delete: {cache.path}")
                continue
            path = Path(cache.path)
            if not path.exists():
                continue
            try:
                shutil.rmtree(path)
                deleted.append(cache.path)
            except OSError as exc:
                errors.append(f"Repository cache delete failed for {cache.path}: {exc}")
        return deleted, errors

    def _safe_cache_path(self, value: str) -> bool:
        root = self.repository_cache_root.resolve()
        path = Path(value).resolve()
        return path != root and path.is_relative_to(root)


def cleanup_plan_checksum(plan: ProjectCleanupPlan) -> str:
    payload = plan.model_dump(mode="json", exclude={"checksum", "generated_at"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_plan_confirmation(plan: ProjectCleanupPlan, confirmation: str) -> None:
    if not plan.checksum or cleanup_plan_checksum(plan) != plan.checksum:
        raise ProjectCleanupPlanError("Cleanup plan checksum is invalid.")
    if confirmation != plan.checksum:
        raise ProjectCleanupPlanError("Confirmation must exactly match the plan checksum.")
    if not plan.safe_to_apply:
        raise ProjectCleanupPlanError(blocked_plan_message(plan))


def blocked_plan_message(plan: ProjectCleanupPlan) -> str:
    blocked = [
        f"{project.project_id}: runs={project.active_run_ids}, "
        f"workflow_tasks={project.active_workflow_task_ids}"
        for project in plan.projects
        if project.blocked
    ]
    return "Cleanup plan contains non-terminal work: " + "; ".join(blocked)


def all_projects_absent(plan: ProjectCleanupPlan) -> bool:
    return all(project.state is ProjectCleanupState.ALREADY_ABSENT for project in plan.projects)


def planned_s3_keys(projects: Sequence[ProjectCleanupProject]) -> list[str]:
    return sorted({key for project in projects for key in project.s3_keys})


def planned_repository_caches(
    projects: Sequence[ProjectCleanupProject],
) -> list[ProjectCleanupRepositoryCache]:
    caches = {cache.path: cache for project in projects for cache in project.repository_caches}
    return [caches[path] for path in sorted(caches)]
