from __future__ import annotations

import os
from dataclasses import dataclass

from guidesync_agent.schemas import (
    TokenUsageSummaryItem,
    ValidationFinding,
)
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
    config = config or token_budget_config_from_env()
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
        role_budget = role_budget_from_env(item.key)
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


def token_budget_config_from_env() -> TokenBudgetConfig:
    return TokenBudgetConfig(
        run_budget=positive_env_int("GUIDESYNC_RUN_TOKEN_BUDGET"),
        workflow_task_budget=positive_env_int("GUIDESYNC_WORKFLOW_TASK_TOKEN_BUDGET"),
        mode=token_budget_mode(),
    )


def token_budget_mode() -> str:
    raw = os.environ.get("GUIDESYNC_TOKEN_BUDGET_MODE", "warn").strip().lower()
    return "fail" if raw in {"fail", "error", "fail_fast"} else "warn"


def role_budget_from_env(role: str) -> int | None:
    normalized = "".join(character if character.isalnum() else "_" for character in role.upper())
    return positive_env_int(f"GUIDESYNC_TOKEN_BUDGET_ROLE_{normalized}")


def positive_env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


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
