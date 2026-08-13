from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext

from guidesync_agent.schemas import (
    AgentLoopObservation,
    AgentLoopToolCall,
    ChangeAnalysisCheckpoint,
    ChangeAnalysisCoverage,
    ChangeAnalysisCoverageDisposition,
    ChangeAnalysisInventory,
    ChangeAnalysisInventoryItem,
    ChangeAnalysisInventoryItemKind,
    ChangeAnalysisWorkflowResult,
    ProjectWorkflowProgress,
    ProjectWorkflowStage,
    ReleaseChangeConfidence,
    ReleaseChangeFinding,
    ReleaseChangeKind,
)
from guidesync_agent.services.change_analysis_checkpoint import (
    covered_keys,
    replace_coverage,
    replace_finding,
    uncovered_inventory,
)
from guidesync_agent.storage import create_project_workflow_store
from guidesync_agent.tools import repository as repository_tools
from guidesync_agent.tools.knowledge import (
    KnowledgeBaseSearchRequest,
    read_knowledge_document_window,
    search_knowledge_base,
)
from guidesync_agent.tools.project_profile import get_project_profile
from guidesync_agent.tools.repository_filesystem import context_from_project
from guidesync_agent.tools.repository_filesystem_observations import (
    execute_repository_filesystem_tool,
    model_visible_content,
)
from guidesync_agent.tools.repository_filesystem_toolset import (
    register_repository_filesystem_tools,
)

MAX_INVENTORY_PAGE = 200
MAX_DIFF_CHARS = 16_000
MAX_REPOSITORY_READ_CHARS = 16_000
MAX_MULTI_READ_CHARS = 16_000


@dataclass
class ChangeAnalysisOrchestratorDeps:
    project_id: str
    run_id: str
    workflow_task_id: str
    inventory: ChangeAnalysisInventory
    checkpoint: ChangeAnalysisCheckpoint
    audience: str
    observations: list[AgentLoopObservation] = field(default_factory=list)
    tool_calls: int = 0


def register_change_analysis_orchestrator_tools(  # noqa: C901, PLR0915
    agent: Any,
) -> None:
    register_repository_filesystem_tools(agent, execute_repository_filesystem)

    @agent.tool
    def list_change_inventory(
        ctx: RunContext[ChangeAnalysisOrchestratorDeps],
        offset: int = 0,
        limit: int = 100,
        uncovered_only: bool = True,
    ) -> dict[str, Any]:
        """List a bounded page of frozen commit/path inventory items."""
        items = (
            uncovered_inventory(ctx.deps.inventory, ctx.deps.checkpoint)
            if uncovered_only
            else ctx.deps.inventory.items
        )
        safe_offset = max(0, offset)
        safe_limit = min(max(1, limit), MAX_INVENTORY_PAGE)
        page = items[safe_offset : safe_offset + safe_limit]
        return {
            "items": [item.model_dump(mode="json") for item in page],
            "offset": safe_offset,
            "limit": safe_limit,
            "total": len(items),
            "has_more": safe_offset + len(page) < len(items),
        }

    @agent.tool
    def read_change_diff(
        ctx: RunContext[ChangeAnalysisOrchestratorDeps],
        inventory_key: str,
        path: str | None = None,
        offset: int = 0,
        limit: int = MAX_DIFF_CHARS,
    ) -> dict[str, Any]:
        """Read a bounded raw diff for one frozen inventory item."""
        item = require_inventory_item(ctx.deps, inventory_key)
        selected_path = validated_diff_path(item, path)
        safe_limit = min(max(1, limit), MAX_DIFF_CHARS)
        result = repository_tools.read_diff_window(
            ctx.deps.project_id,
            item.repository_id,
            path=selected_path,
            base_ref=item.base_ref,
            head_ref=item.head_ref,
            offset=max(0, offset),
            limit=safe_limit,
        )
        ctx.deps.tool_calls += 1
        return {
            **result.model_dump(mode="json"),
            "inventory_key": inventory_key,
            "evidence_ref": diff_evidence_ref(item, selected_path),
        }

    @agent.tool
    def read_project_profile(
        ctx: RunContext[ChangeAnalysisOrchestratorDeps],
    ) -> dict[str, Any]:
        """Read the latest project profile brief and documentation categories."""
        profile = get_project_profile(ctx.deps.project_id)
        ctx.deps.tool_calls += 1
        return {
            "profile": profile.model_dump(mode="json") if profile else None,
            "evidence_ref": f"profile:{profile.id}" if profile else None,
        }

    @agent.tool
    def search_knowledge(
        ctx: RunContext[ChangeAnalysisOrchestratorDeps],
        query: str,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Search indexed project documentation for a focused release-change question."""
        results = search_knowledge_base(
            KnowledgeBaseSearchRequest(
                project_id=ctx.deps.project_id,
                query=query,
                audience=ctx.deps.audience,
                limit=min(max(1, limit), 20),
            )
        )
        ctx.deps.tool_calls += 1
        return {
            "results": [item.model_dump(mode="json") for item in results],
            "evidence_refs": [f"knowledge:{item.node.id}" for item in results],
        }

    @agent.tool
    def read_knowledge_document(
        ctx: RunContext[ChangeAnalysisOrchestratorDeps],
        document_id: str,
        offset: int = 0,
        limit: int = 16000,
    ) -> dict[str, Any]:
        """Read a bounded window from one indexed knowledge document."""
        result = read_knowledge_document_window(
            document_id,
            offset=max(0, offset),
            limit=min(max(1, limit), 16_000),
        )
        ctx.deps.tool_calls += 1
        return {
            **result.model_dump(mode="json"),
            "evidence_ref": f"knowledge:{document_id}",
        }

    @agent.tool
    def list_release_findings(
        ctx: RunContext[ChangeAnalysisOrchestratorDeps],
    ) -> dict[str, Any]:
        """List the durable semantic findings already saved for this analysis."""
        return {
            "findings": [
                finding.model_dump(mode="json") for finding in ctx.deps.checkpoint.findings
            ],
            "coverage": [
                coverage.model_dump(mode="json") for coverage in ctx.deps.checkpoint.coverage
            ],
        }

    @agent.tool
    def save_release_finding(  # noqa: PLR0913 - flat model-facing contract
        ctx: RunContext[ChangeAnalysisOrchestratorDeps],
        finding_id: str,
        title: str,
        kind: str,
        technical_summary: str,
        user_impact: str,
        coverage_keys: list[str],
        evidence_refs: list[str],
        documentation_search_intents: list[str] | None = None,
        risk_notes: list[str] | None = None,
        release_note_eligible: bool = True,
        confidence: str = "medium",
    ) -> dict[str, Any]:
        """Persist one semantic release finding and its inventory coverage."""
        clean_finding_id = validated_identifier(finding_id)
        finding = ReleaseChangeFinding(
            id=clean_finding_id,
            title=required_text(title, "title"),
            kind=ReleaseChangeKind(kind),
            technical_summary=required_text(technical_summary, "technical_summary"),
            user_impact=required_text(user_impact, "user_impact"),
            coverage_keys=validated_inventory_keys(
                ctx.deps,
                coverage_keys,
                finding_id=clean_finding_id,
            ),
            evidence_refs=unique_non_empty(evidence_refs),
            documentation_search_intents=unique_non_empty(
                documentation_search_intents or []
            ),
            risk_notes=unique_non_empty(risk_notes or []),
            release_note_eligible=release_note_eligible,
            confidence=ReleaseChangeConfidence(confidence.strip().lower()),
        )
        replace_finding(ctx.deps.checkpoint, finding)
        persist_checkpoint(ctx.deps)
        return {
            "status": "saved",
            "finding_id": finding.id,
            "covered_keys": finding.coverage_keys,
            "remaining": len(
                uncovered_inventory(ctx.deps.inventory, ctx.deps.checkpoint)
            ),
        }

    @agent.tool
    def mark_no_release_note(
        ctx: RunContext[ChangeAnalysisOrchestratorDeps],
        coverage_keys: list[str],
        reason: str,
    ) -> dict[str, Any]:
        """Persist explicit coverage for changes that do not belong in release notes."""
        keys = validated_inventory_keys(ctx.deps, coverage_keys)
        for key in keys:
            replace_coverage(
                ctx.deps.checkpoint,
                ChangeAnalysisCoverage(
                    key=key,
                    disposition=ChangeAnalysisCoverageDisposition.NO_RELEASE_NOTE,
                    reason=required_text(reason, "reason"),
                ),
            )
        persist_checkpoint(ctx.deps)
        return {
            "status": "saved",
            "covered_keys": keys,
            "remaining": len(
                uncovered_inventory(ctx.deps.inventory, ctx.deps.checkpoint)
            ),
        }


def execute_repository_filesystem(
    ctx: RunContext[ChangeAnalysisOrchestratorDeps],
    call: AgentLoopToolCall,
) -> str:
    observation = execute_repository_filesystem_tool(
        context_from_project(ctx.deps.project_id),
        call,
        max_read_chars=MAX_REPOSITORY_READ_CHARS,
        max_multiple_read_chars=MAX_MULTI_READ_CHARS,
    )
    ctx.deps.observations.append(observation)
    ctx.deps.tool_calls += 1
    return model_visible_content(observation)


def persist_checkpoint(deps: ChangeAnalysisOrchestratorDeps) -> None:
    store = create_project_workflow_store()
    task = store.get(deps.workflow_task_id)
    if task is None:
        raise ValueError(f"Workflow task not found: {deps.workflow_task_id}")
    task_result = ChangeAnalysisWorkflowResult(
        inventory=deps.inventory,
        checkpoint=deps.checkpoint,
    )
    store.save(
        task.model_copy(
            update={
                "result": task_result,
                "progress": ProjectWorkflowProgress(
                    stage=ProjectWorkflowStage.ANALYZING,
                    message="Building semantic release findings",
                    completed_items=len(covered_keys(deps.checkpoint)),
                    total_items=len(deps.inventory.items),
                ),
            }
        )
    )


def require_inventory_item(
    deps: ChangeAnalysisOrchestratorDeps,
    key: str,
) -> ChangeAnalysisInventoryItem:
    item = next((item for item in deps.inventory.items if item.key == key), None)
    if item is None:
        raise ValueError(f"Unknown inventory key: {key}")
    return item


def validated_inventory_keys(
    deps: ChangeAnalysisOrchestratorDeps,
    keys: list[str],
    *,
    finding_id: str | None = None,
) -> list[str]:
    validated = unique_non_empty(keys)
    if not validated:
        raise ValueError("At least one coverage key is required.")
    known = {item.key for item in deps.inventory.items}
    unknown = [key for key in validated if key not in known]
    if unknown:
        raise ValueError(f"Unknown inventory keys: {', '.join(unknown[:5])}")
    coverage_by_key = {item.key: item for item in deps.checkpoint.coverage}
    conflicts = [
        key
        for key in validated
        if (coverage := coverage_by_key.get(key)) is not None
        and coverage.disposition is not ChangeAnalysisCoverageDisposition.UNRESOLVED
        and coverage.finding_id != finding_id
    ]
    if conflicts:
        raise ValueError(
            "Inventory keys already have durable coverage: "
            + ", ".join(conflicts[:5])
        )
    return validated


def validated_diff_path(item: ChangeAnalysisInventoryItem, path: str | None) -> str | None:
    if item.kind is ChangeAnalysisInventoryItemKind.PATH:
        return item.path
    if path is None:
        return None
    if path not in item.related_paths:
        raise ValueError(f"Path is not part of commit inventory item {item.key}: {path}")
    return path


def diff_evidence_ref(item: ChangeAnalysisInventoryItem, path: str | None) -> str:
    path_part = path or "repository"
    return f"diff:{item.repository_id}:{path_part}:{item.base_ref}:{item.head_ref}"


def validated_identifier(value: str) -> str:
    clean = value.strip()
    if not clean or len(clean) > 120:
        raise ValueError("finding_id must contain 1-120 characters.")
    return clean


def required_text(value: str, field_name: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field_name} is required.")
    return clean


def unique_non_empty(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))
