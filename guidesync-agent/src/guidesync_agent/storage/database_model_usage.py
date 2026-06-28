from __future__ import annotations

from sqlalchemy import create_engine, insert, select, update

from guidesync_agent.models import (
    model_call_ledger_table,
)
from guidesync_agent.schemas import (
    ModelCallLedgerEntry,
    RunTokenUsageSummary,
    WorkflowTaskTokenUsageSummary,
)

from .serialization import (
    ledger_total_usage_tokens,
    model_call_ledger_from_row,
    model_call_ledger_values,
    summarize_usage_items,
    usage_entry_warnings,
)


class DatabaseModelUsageStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        return None

    def record(self, entry: ModelCallLedgerEntry) -> ModelCallLedgerEntry:
        self.initialize()
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(model_call_ledger_table.c.id).where(
                    model_call_ledger_table.c.id == entry.id
                )
            ).one_or_none()
            values = model_call_ledger_values(entry)
            if existing is None:
                connection.execute(insert(model_call_ledger_table).values(**values))
            else:
                connection.execute(
                    update(model_call_ledger_table)
                    .where(model_call_ledger_table.c.id == entry.id)
                    .values(**values)
                )
        return entry

    def list_for_run(
        self,
        run_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ModelCallLedgerEntry]:
        self.initialize()
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(model_call_ledger_table)
                .where(model_call_ledger_table.c.run_id == run_id)
                .order_by(model_call_ledger_table.c.started_at, model_call_ledger_table.c.id)
                .limit(limit)
                .offset(offset)
            ).all()
        return [model_call_ledger_from_row(row) for row in rows]

    def list_for_workflow_task(
        self,
        workflow_task_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ModelCallLedgerEntry]:
        self.initialize()
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(model_call_ledger_table)
                .where(model_call_ledger_table.c.workflow_task_id == workflow_task_id)
                .order_by(model_call_ledger_table.c.started_at, model_call_ledger_table.c.id)
                .limit(limit)
                .offset(offset)
            ).all()
        return [model_call_ledger_from_row(row) for row in rows]

    def summarize_run(self, run_id: str) -> RunTokenUsageSummary:
        entries = self.list_for_run(run_id, limit=10_000)
        by_role = summarize_usage_items(entries, lambda entry: entry.role.value)
        by_provider = summarize_usage_items(entries, lambda entry: entry.provider.value)
        by_model = summarize_usage_items(entries, lambda entry: entry.model)
        by_workflow_task = summarize_usage_items(
            [entry for entry in entries if entry.workflow_task_id],
            lambda entry: entry.workflow_task_id or "unknown",
        )
        return RunTokenUsageSummary(
            run_id=run_id,
            total_tokens=sum(ledger_total_usage_tokens(entry.usage) for entry in entries),
            estimated_tokens=sum(
                entry.usage.locally_estimated_total_tokens or 0 for entry in entries
            ),
            calls=len(entries),
            by_workflow_task=by_workflow_task,
            by_role=by_role,
            by_provider=by_provider,
            by_model=by_model,
            warnings=[
                warning
                for entry in entries
                for warning in usage_entry_warnings(entry)
            ],
        )

    def summarize_workflow_task(
        self,
        workflow_task_id: str,
    ) -> WorkflowTaskTokenUsageSummary:
        entries = self.list_for_workflow_task(workflow_task_id, limit=10_000)
        return WorkflowTaskTokenUsageSummary(
            workflow_task_id=workflow_task_id,
            run_ids=sorted({entry.run_id for entry in entries if entry.run_id}),
            total_tokens=sum(ledger_total_usage_tokens(entry.usage) for entry in entries),
            estimated_tokens=sum(
                entry.usage.locally_estimated_total_tokens or 0 for entry in entries
            ),
            calls=len(entries),
            by_role=summarize_usage_items(entries, lambda entry: entry.role.value),
            by_provider=summarize_usage_items(entries, lambda entry: entry.provider.value),
            by_model=summarize_usage_items(entries, lambda entry: entry.model),
            warnings=[
                warning
                for entry in entries
                for warning in usage_entry_warnings(entry)
            ],
        )
