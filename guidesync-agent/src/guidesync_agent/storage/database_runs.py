from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine, insert, select, update

from guidesync_agent.models import (
    report_runs_table,
    run_artifacts_table,
    run_events_table,
)
from guidesync_agent.schemas import (
    GuideSyncRunResult,
    PublicationReport,
    RunSummary,
)

from .serialization import (
    replace_run_artifacts,
    run_result_from_snapshot,
    run_summary,
    upsert_report_run,
)


class DatabaseRunStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        return None

    def save(
        self,
        result: GuideSyncRunResult,
        publication_report: PublicationReport | None = None,
    ) -> None:
        self.initialize()
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(report_runs_table.c.created_at).where(
                    report_runs_table.c.id == result.run_id
                )
            ).one_or_none()
            upsert_report_run(
                connection,
                result,
                publication_report,
                now,
                existing.created_at if existing else None,
            )
            replace_run_artifacts(connection, result, now)

    def get(self, run_id: str) -> GuideSyncRunResult | None:
        self.initialize()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(report_runs_table.c.result_snapshot).where(report_runs_table.c.id == run_id)
            ).one_or_none()
        if row is None:
            return None
        return run_result_from_snapshot(row.result_snapshot)

    def run_exists(self, run_id: str) -> bool:
        with self.engine.begin() as connection:
            return (
                connection.execute(
                    select(report_runs_table.c.id).where(report_runs_table.c.id == run_id)
                ).scalar_one_or_none()
                is not None
            )

    def get_publication_report(self, run_id: str) -> PublicationReport | None:
        with self.engine.begin() as connection:
            snapshot = connection.execute(
                select(report_runs_table.c.publication_snapshot).where(
                    report_runs_table.c.id == run_id
                )
            ).scalar_one_or_none()
        if snapshot is None:
            return None
        return PublicationReport.model_validate(snapshot)

    def get_artifact_uri(self, run_id: str, filename: str) -> str | None:
        with self.engine.begin() as connection:
            return connection.execute(
                select(run_artifacts_table.c.uri).where(
                    run_artifacts_table.c.run_id == run_id,
                    run_artifacts_table.c.artifact_type == filename,
                )
            ).scalar_one_or_none()

    def list_runs(self, project_id: str | None = None) -> list[RunSummary]:
        self.initialize()
        query = select(
            report_runs_table.c.result_snapshot,
            report_runs_table.c.publication_snapshot,
            report_runs_table.c.created_at,
            report_runs_table.c.updated_at,
        ).order_by(report_runs_table.c.updated_at.desc())
        if project_id:
            query = query.where(report_runs_table.c.project_id == project_id)
        with self.engine.begin() as connection:
            rows = connection.execute(query).all()
        return [
            run_summary(
                run_result_from_snapshot(row.result_snapshot),
                created_at=row.created_at,
                updated_at=row.updated_at,
                publication_available=row.publication_snapshot is not None,
            )
            for row in rows
        ]

    def claim_next_queued_run(self) -> GuideSyncRunResult | None:
        self.initialize()
        now = datetime.now(UTC)
        result: GuideSyncRunResult | None = None
        with self.engine.begin() as connection:
            row = connection.execute(
                select(report_runs_table.c.id, report_runs_table.c.result_snapshot)
                .where(report_runs_table.c.status == "queued")
                .order_by(report_runs_table.c.created_at)
                .limit(1)
            ).one_or_none()
            if row is None:
                return None
            result = run_result_from_snapshot(row.result_snapshot)
            result.status = "running"
            claimed = connection.execute(
                update(report_runs_table)
                .where(
                    report_runs_table.c.id == row.id,
                    report_runs_table.c.status == "queued",
                )
                .values(
                    status="running",
                    started_at=now,
                    updated_at=now,
                    result_snapshot=result.model_dump(mode="json"),
                )
            )
            if claimed.rowcount != 1:
                return None
        self.record_run_event(result.run_id, "running", "Run claimed by worker.", "worker")
        return result

    def record_run_event(
        self,
        run_id: str,
        status: str,
        message: str,
        stage: str | None = None,
    ) -> None:
        self.initialize()
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            connection.execute(
                insert(run_events_table).values(
                    id=f"event-{uuid4().hex[:12]}",
                    run_id=run_id,
                    status=status,
                    stage=stage,
                    message=message,
                    created_at=now,
                )
            )
