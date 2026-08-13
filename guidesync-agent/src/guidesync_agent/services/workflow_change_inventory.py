from __future__ import annotations

from guidesync_agent.evidence import collect_evidence
from guidesync_agent.schemas import (
    ChangeAnalysisInventory,
    ChangeAnalysisInventoryItem,
    ChangeAnalysisInventoryItemKind,
    CommitEvidence,
    GuideSyncRunResult,
)
from guidesync_agent.storage import create_run_store
from guidesync_agent.tools.repository import list_changed_files
from guidesync_agent.workflows.documentation_update import historical_analysis_refs


def collect_change_analysis_inventory(run: GuideSyncRunResult) -> ChangeAnalysisInventory:
    evidence = collect_evidence(run.request.repositories, run.request.documentation)
    create_run_store().save(run.model_copy(update={"evidence": evidence}))
    items: list[ChangeAnalysisInventoryItem] = []
    for repository in run.request.repositories:
        if not repository.project_id or not repository.repository_id:
            continue
        repository_commits = [
            commit for commit in evidence.commits if commit.repo == repository.name
        ]
        commit_items = commit_inventory_items(
            repository.repository_id,
            repository_commits,
        )
        if commit_items:
            items.extend(commit_items)
            continue
        base_ref, head_ref = historical_analysis_refs(repository, evidence)
        result = list_changed_files(
            repository.project_id,
            repository.repository_id,
            base_ref=base_ref,
            head_ref=head_ref,
        )
        if result.error is not None:
            raise RuntimeError(result.error.message)
        items.extend(
            ChangeAnalysisInventoryItem(
                key=f"path:{repository.repository_id}:{changed_file.path}",
                kind=ChangeAnalysisInventoryItemKind.PATH,
                repository_id=repository.repository_id,
                summary=f"{changed_file.status} {changed_file.path}",
                path=changed_file.path,
                status=changed_file.status,
                base_ref=result.base_ref,
                head_ref=result.head_ref,
            )
            for changed_file in result.files
        )
    return ChangeAnalysisInventory(run_id=run.run_id, items=deduplicated_inventory(items))


def commit_inventory_items(
    repository_id: str,
    commits: list[CommitEvidence],
) -> list[ChangeAnalysisInventoryItem]:
    return [
        ChangeAnalysisInventoryItem(
            key=f"commit:{repository_id}:{commit.sha}",
            kind=ChangeAnalysisInventoryItemKind.COMMIT,
            repository_id=repository_id,
            summary=commit_summary(commit),
            commit_sha=commit.sha,
            related_paths=commit.files,
            base_ref=f"{commit.sha}^",
            head_ref=commit.sha,
        )
        for commit in commits
    ]


def commit_summary(commit: CommitEvidence) -> str:
    body = " ".join(commit.body.split())
    summary = f"{commit.short_sha} {commit.subject}"
    return f"{summary} — {body[:500]}" if body else summary


def deduplicated_inventory(
    items: list[ChangeAnalysisInventoryItem],
) -> list[ChangeAnalysisInventoryItem]:
    return list({item.key: item for item in items}.values())
