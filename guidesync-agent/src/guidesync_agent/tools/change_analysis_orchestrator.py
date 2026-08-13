from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import BeforeValidator
from pydantic_ai import ModelRetry, RunContext

from guidesync_agent.schemas import (
    AgentLoopObservation,
    AgentLoopToolCall,
    ChangeAnalysisCheckpoint,
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

DEFAULT_INVENTORY_PAGE = 25
MAX_INVENTORY_PAGE = 100
MAX_RELATED_PATH_PAGE = 50
MAX_FINDINGS_PAGE = 50
MAX_DIFF_CHARS = 16_000
MAX_REPOSITORY_READ_CHARS = 16_000
MAX_MULTI_READ_CHARS = 16_000

ModelReleaseChangeKind = Annotated[
    ReleaseChangeKind,
    BeforeValidator(lambda value: normalized_enum_input(value)),
]
ModelReleaseChangeConfidence = Annotated[
    ReleaseChangeConfidence,
    BeforeValidator(lambda value: normalized_enum_input(value)),
]


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
        limit: int = DEFAULT_INVENTORY_PAGE,
        uncovered_only: bool = True,
    ) -> dict[str, Any]:
        """List compact frozen inventory summaries; read one item for full path details."""
        items = (
            uncovered_inventory(ctx.deps.inventory, ctx.deps.checkpoint)
            if uncovered_only
            else ctx.deps.inventory.items
        )
        safe_offset = max(0, offset)
        safe_limit = min(max(1, limit), MAX_INVENTORY_PAGE)
        page = items[safe_offset : safe_offset + safe_limit]
        has_more = safe_offset + len(page) < len(items)
        ctx.deps.tool_calls += 1
        return {
            "items": [inventory_item_summary(item) for item in page],
            "offset": safe_offset,
            "limit": safe_limit,
            "total": len(items),
            "has_more": has_more,
            "next_offset": safe_offset + len(page) if has_more else None,
        }

    @agent.tool
    def read_change_inventory_item(
        ctx: RunContext[ChangeAnalysisOrchestratorDeps],
        inventory_key: str,
        related_paths_offset: int = 0,
        related_paths_limit: int = 25,
    ) -> dict[str, Any]:
        """Read one frozen inventory item with a bounded related-path page."""
        item = require_inventory_item(ctx.deps, inventory_key)
        safe_offset = max(0, related_paths_offset)
        safe_limit = min(max(1, related_paths_limit), MAX_RELATED_PATH_PAGE)
        related_paths = item.related_paths[safe_offset : safe_offset + safe_limit]
        has_more = safe_offset + len(related_paths) < len(item.related_paths)
        ctx.deps.tool_calls += 1
        return {
            **item.model_dump(mode="json", exclude={"related_paths"}),
            "related_paths": related_paths,
            "related_paths_offset": safe_offset,
            "related_paths_limit": safe_limit,
            "related_paths_total": len(item.related_paths),
            "related_paths_has_more": has_more,
            "related_paths_next_offset": (
                safe_offset + len(related_paths) if has_more else None
            ),
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
    def list_change_artifacts(
        ctx: RunContext[ChangeAnalysisOrchestratorDeps],
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List a bounded page of durable change-analysis artifacts already saved."""
        safe_offset = max(0, offset)
        safe_limit = min(max(1, limit), MAX_FINDINGS_PAGE)
        findings = ctx.deps.checkpoint.findings
        page = findings[safe_offset : safe_offset + safe_limit]
        has_more = safe_offset + len(page) < len(findings)
        ctx.deps.tool_calls += 1
        return {
            "artifacts": [finding.model_dump(mode="json") for finding in page],
            "offset": safe_offset,
            "limit": safe_limit,
            "total": len(findings),
            "has_more": has_more,
            "next_offset": safe_offset + len(page) if has_more else None,
            "covered_total": len(covered_keys(ctx.deps.checkpoint)),
            "remaining_total": len(
                uncovered_inventory(ctx.deps.inventory, ctx.deps.checkpoint)
            ),
        }

    @agent.tool(sequential=True)
    def save_change_artifact(  # noqa: PLR0913 - flat model-facing contract
        ctx: RunContext[ChangeAnalysisOrchestratorDeps],
        artifact_id: str,
        title: str,
        kind: ModelReleaseChangeKind,
        technical_summary: str,
        user_impact: str,
        coverage_keys: list[str],
        evidence_refs: list[str],
        documentation_search_intents: list[str] | None = None,
        risk_notes: list[str] | None = None,
        release_note_eligible: bool = True,
        confidence: ModelReleaseChangeConfidence = ReleaseChangeConfidence.MEDIUM,
    ) -> dict[str, Any]:
        """Persist one analysis artifact and its inventory coverage."""
        try:
            clean_finding_id = validated_identifier(artifact_id)
            finding = ReleaseChangeFinding(
                id=clean_finding_id,
                title=required_text(title, "title"),
                kind=release_change_kind(kind),
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
                confidence=release_change_confidence(confidence),
            )
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc
        replace_finding(ctx.deps.checkpoint, finding)
        persist_checkpoint(ctx.deps)
        return {
            "status": "saved",
            "artifact_id": finding.id,
            "covered_keys": finding.coverage_keys,
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


def inventory_item_summary(item: ChangeAnalysisInventoryItem) -> dict[str, Any]:
    return {
        "key": item.key,
        "kind": item.kind.value,
        "repository_id": item.repository_id,
        "summary": item.summary,
        "path": item.path,
        "status": item.status,
        "commit_sha": item.commit_sha,
        "related_path_count": len(item.related_paths),
    }


def validated_inventory_keys(
    deps: ChangeAnalysisOrchestratorDeps,
    keys: list[str],
    *,
    finding_id: str | None = None,
) -> list[str]:
    validated = unique_non_empty(keys)
    if not validated:
        if not deps.inventory.items:
            return []
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
        and coverage.disposition is ChangeAnalysisCoverageDisposition.FINDING
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
        raise ValueError("artifact_id must contain 1-120 characters.")
    return clean


def normalized_enum_input(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


def release_change_kind(value: ReleaseChangeKind | str) -> ReleaseChangeKind:
    try:
        return ReleaseChangeKind(normalized_enum_input(value))
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ReleaseChangeKind)
        raise ValueError(f"kind must be one of: {allowed}.") from exc


def release_change_confidence(
    value: ReleaseChangeConfidence | str,
) -> ReleaseChangeConfidence:
    try:
        return ReleaseChangeConfidence(normalized_enum_input(value))
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ReleaseChangeConfidence)
        raise ValueError(f"confidence must be one of: {allowed}.") from exc


def required_text(value: str, field_name: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field_name} is required.")
    return clean


def unique_non_empty(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))
