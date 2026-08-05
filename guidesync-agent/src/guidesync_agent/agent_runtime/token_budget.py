from __future__ import annotations

from dataclasses import dataclass

from guidesync_agent.schemas import (
    TokenUsageSummaryItem,
    ValidationFinding,
)
from guidesync_agent.settings import get_settings
from guidesync_agent.storage import create_model_usage_store


@dataclass(frozen=True)
class TokenBudgetConfig:
    run_budget: int | None = None
    workflow_task_budget: int | None = None
    mode: str = "warn"

    @property
    def severity(self) -> str:
        return "error" if self.mode == "fail" else "warning"


def evaluate_token_budgets(
    run_id: str,
    *,
    workflow_task_id: str | None = None,
    config: TokenBudgetConfig | None = None,
) -> list[ValidationFinding]:
    config = config or token_budget_config_from_settings()
    findings: list[ValidationFinding] = []
    store = create_model_usage_store()
    run_summary = store.summarize_run(run_id)
    if config.run_budget is not None:
        findings.extend(
            budget_findings_for_total(
                scope="run",
                scope_id=run_id,
                total_tokens=run_summary.total_tokens,
                budget=config.run_budget,
                severity=config.severity,
            )
        )
    if workflow_task_id and config.workflow_task_budget is not None:
        task_summary = store.summarize_workflow_task(workflow_task_id)
        findings.extend(
            budget_findings_for_total(
                scope="workflow-task",
                scope_id=workflow_task_id,
                total_tokens=task_summary.total_tokens,
                budget=config.workflow_task_budget,
                severity=config.severity,
            )
        )
    for item in run_summary.by_role:
        role_budget = get_settings().token_budget.role_budget(item.key)
        if role_budget is None:
            continue
        findings.extend(
            budget_findings_for_item(
                item,
                budget=role_budget,
                severity=config.severity,
            )
        )
    return findings


def token_budget_config_from_settings() -> TokenBudgetConfig:
    settings = get_settings().token_budget
    return TokenBudgetConfig(
        run_budget=settings.run_budget,
        workflow_task_budget=settings.workflow_task_budget,
        mode=settings.normalized_mode,
    )


def budget_findings_for_item(
    item: TokenUsageSummaryItem,
    *,
    budget: int,
    severity: str,
) -> list[ValidationFinding]:
    return budget_findings_for_total(
        scope="role",
        scope_id=item.key,
        total_tokens=item.total_tokens,
        budget=budget,
        severity=severity,
    )


def budget_findings_for_total(
    *,
    scope: str,
    scope_id: str,
    total_tokens: int,
    budget: int,
    severity: str,
) -> list[ValidationFinding]:
    if total_tokens <= budget:
        return []
    return [
        ValidationFinding(
            severity=severity,
            check=f"token-budget.{scope}",
            message=(
                f"Token budget exceeded for {scope} `{scope_id}`: "
                f"{total_tokens} tokens used, budget {budget}."
            ),
        )
    ]
