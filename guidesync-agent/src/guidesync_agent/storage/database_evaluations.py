from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, and_, create_engine, func, insert, select, update

from guidesync_agent.models import (
    evaluation_comparisons_table,
    evaluation_experiments_table,
    evaluation_runs_table,
)
from guidesync_agent.schemas import (
    AblationComparisonReport,
    EvaluationComparisonPage,
    EvaluationComparisonRecord,
    EvaluationExperimentManifest,
    EvaluationExperimentPage,
    EvaluationExperimentRecord,
    EvaluationExperimentRun,
    EvaluationRunPage,
    EvaluationRunRecord,
    EvaluationRunStatus,
)


class DatabaseEvaluationStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        return None

    def save_experiment(
        self,
        project_id: str,
        manifest: EvaluationExperimentManifest,
        manifest_checksum: str,
    ) -> EvaluationExperimentRecord:
        now = datetime.now(UTC)
        payload = manifest.model_dump(mode="json")
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(evaluation_experiments_table).where(
                    evaluation_experiments_table.c.id == manifest.id
                )
            ).one_or_none()
            if existing is None:
                connection.execute(
                    insert(evaluation_experiments_table).values(
                        id=manifest.id,
                        project_id=project_id,
                        manifest_checksum=manifest_checksum,
                        manifest=payload,
                        created_at=now,
                        updated_at=now,
                    )
                )
            elif (
                existing.project_id != project_id
                or existing.manifest_checksum != manifest_checksum
                or existing.manifest != payload
            ):
                raise ValueError(
                    f"evaluation experiment {manifest.id} is immutable and already exists"
                )
            row = connection.execute(
                select(evaluation_experiments_table).where(
                    evaluation_experiments_table.c.id == manifest.id
                )
            ).one()
            return experiment_record(connection, row)

    def get_experiment(self, experiment_id: str) -> EvaluationExperimentRecord | None:
        with self.engine.begin() as connection:
            row = connection.execute(
                select(evaluation_experiments_table).where(
                    evaluation_experiments_table.c.id == experiment_id
                )
            ).one_or_none()
            return experiment_record(connection, row) if row else None

    def list_experiments(
        self,
        project_id: str,
        *,
        limit: int,
        offset: int,
    ) -> EvaluationExperimentPage:
        where = evaluation_experiments_table.c.project_id == project_id
        with self.engine.begin() as connection:
            total = connection.scalar(
                select(func.count()).select_from(evaluation_experiments_table).where(where)
            )
            rows = connection.execute(
                select(evaluation_experiments_table)
                .where(where)
                .order_by(
                    evaluation_experiments_table.c.updated_at.desc(),
                    evaluation_experiments_table.c.id,
                )
                .limit(limit)
                .offset(offset)
            ).all()
            items = [experiment_record(connection, row) for row in rows]
        return EvaluationExperimentPage(
            items=items,
            total=total or 0,
            limit=limit,
            offset=offset,
        )

    def save_run(self, run: EvaluationExperimentRun) -> EvaluationRunRecord:
        now = datetime.now(UTC)
        manifest = run.manifest
        payload = run.model_dump(mode="json")
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(evaluation_runs_table).where(
                    evaluation_runs_table.c.id == manifest.id
                )
            ).one_or_none()
            if existing is None:
                connection.execute(
                    insert(evaluation_runs_table).values(
                        id=manifest.id,
                        experiment_id=manifest.experiment_id,
                        case_id=manifest.case_id,
                        condition_id=manifest.condition_id,
                        repetition=manifest.repetition,
                        status=run.status.value,
                        case_checksum=manifest.case_checksum,
                        condition_checksum=manifest.condition_checksum,
                        configuration_checksum=manifest.configuration_checksum,
                        experiment_checksum=manifest.experiment_checksum,
                        payload=payload,
                        created_at=now,
                        updated_at=now,
                    )
                )
                touch_experiment(connection, manifest.experiment_id, now)
            elif existing.payload != payload:
                raise ValueError(f"evaluation run {manifest.id} is immutable and already exists")
            row = connection.execute(
                select(evaluation_runs_table).where(
                    evaluation_runs_table.c.id == manifest.id
                )
            ).one()
            return run_record(row)

    def list_runs(
        self,
        experiment_id: str,
        *,
        case_id: str | None,
        condition_id: str | None,
        status: EvaluationRunStatus | None,
        limit: int,
        offset: int,
    ) -> EvaluationRunPage:
        filters = [evaluation_runs_table.c.experiment_id == experiment_id]
        if case_id:
            filters.append(evaluation_runs_table.c.case_id == case_id)
        if condition_id:
            filters.append(evaluation_runs_table.c.condition_id == condition_id)
        if status:
            filters.append(evaluation_runs_table.c.status == status.value)
        where = and_(*filters)
        with self.engine.begin() as connection:
            total = connection.scalar(
                select(func.count()).select_from(evaluation_runs_table).where(where)
            )
            rows = connection.execute(
                select(evaluation_runs_table)
                .where(where)
                .order_by(
                    evaluation_runs_table.c.case_id,
                    evaluation_runs_table.c.condition_id,
                    evaluation_runs_table.c.repetition,
                )
                .limit(limit)
                .offset(offset)
            ).all()
        return EvaluationRunPage(
            items=[run_record(row) for row in rows],
            total=total or 0,
            limit=limit,
            offset=offset,
        )

    def save_comparison(
        self,
        comparison_id: str,
        report: AblationComparisonReport,
    ) -> EvaluationComparisonRecord:
        now = datetime.now(UTC)
        payload = report.model_dump(mode="json")
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(evaluation_comparisons_table).where(
                    evaluation_comparisons_table.c.id == comparison_id
                )
            ).one_or_none()
            if existing is None:
                connection.execute(
                    insert(evaluation_comparisons_table).values(
                        id=comparison_id,
                        experiment_id=report.experiment_id,
                        full_condition_id=report.full_condition_id,
                        ablation_condition_id=report.ablation_condition_id,
                        payload=payload,
                        created_at=now,
                        updated_at=now,
                    )
                )
                touch_experiment(connection, report.experiment_id, now)
            elif existing.payload != payload:
                raise ValueError(
                    f"evaluation comparison {comparison_id} is immutable and already exists"
                )
            row = connection.execute(
                select(evaluation_comparisons_table).where(
                    evaluation_comparisons_table.c.id == comparison_id
                )
            ).one()
            return comparison_record(row)

    def list_comparisons(
        self,
        experiment_id: str,
        *,
        limit: int,
        offset: int,
    ) -> EvaluationComparisonPage:
        where = evaluation_comparisons_table.c.experiment_id == experiment_id
        with self.engine.begin() as connection:
            total = connection.scalar(
                select(func.count())
                .select_from(evaluation_comparisons_table)
                .where(where)
            )
            rows = connection.execute(
                select(evaluation_comparisons_table)
                .where(where)
                .order_by(evaluation_comparisons_table.c.ablation_condition_id)
                .limit(limit)
                .offset(offset)
            ).all()
        return EvaluationComparisonPage(
            items=[comparison_record(row) for row in rows],
            total=total or 0,
            limit=limit,
            offset=offset,
        )


def experiment_record(
    connection: Connection,
    row: Any,
) -> EvaluationExperimentRecord:
    experiment_id = row.id
    run_counts = connection.execute(
        select(
            func.count().label("total"),
            func.count()
            .filter(evaluation_runs_table.c.status == EvaluationRunStatus.COMPLETED.value)
            .label("completed"),
            func.count()
            .filter(evaluation_runs_table.c.status == EvaluationRunStatus.FAILED.value)
            .label("failed"),
        ).where(evaluation_runs_table.c.experiment_id == experiment_id)
    ).one()
    comparison_count = connection.scalar(
        select(func.count())
        .select_from(evaluation_comparisons_table)
        .where(evaluation_comparisons_table.c.experiment_id == experiment_id)
    )
    return EvaluationExperimentRecord(
        project_id=row.project_id,
        manifest=EvaluationExperimentManifest.model_validate(row.manifest),
        manifest_checksum=row.manifest_checksum,
        run_count=run_counts.total,
        completed_run_count=run_counts.completed,
        failed_run_count=run_counts.failed,
        comparison_count=comparison_count or 0,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def run_record(row: Any) -> EvaluationRunRecord:
    run = EvaluationExperimentRun.model_validate(row.payload)
    return EvaluationRunRecord(
        experiment_id=row.experiment_id,
        run=run,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def comparison_record(row: Any) -> EvaluationComparisonRecord:
    return EvaluationComparisonRecord(
        id=row.id,
        experiment_id=row.experiment_id,
        report=AblationComparisonReport.model_validate(row.payload),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def touch_experiment(
    connection: Connection,
    experiment_id: str,
    updated_at: datetime,
) -> None:
    connection.execute(
        update(evaluation_experiments_table)
        .where(evaluation_experiments_table.c.id == experiment_id)
        .values(updated_at=updated_at)
    )
