from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext

from guidesync_agent.schemas import (
    AnalysisArtifactManifest,
    CommitEvidence,
    DocumentationEvidence,
    EvidenceBundle,
    ScreenshotPolicy,
)
from guidesync_agent.settings import get_settings
from guidesync_agent.tools.browser import BrowserToolConfig

_EVIDENCE_SETTINGS = get_settings().model_evidence
MODEL_EVIDENCE_MAX_COMMITS = _EVIDENCE_SETTINGS.max_commits
MODEL_EVIDENCE_MAX_COMMIT_BODY_CHARS = _EVIDENCE_SETTINGS.max_commit_body_chars
MODEL_EVIDENCE_MAX_FILES = _EVIDENCE_SETTINGS.max_files
MODEL_EVIDENCE_MAX_FILE_STATS = _EVIDENCE_SETTINGS.max_file_stats
MODEL_EVIDENCE_MAX_DIFF_HINTS = _EVIDENCE_SETTINGS.max_diff_hints
MODEL_EVIDENCE_MAX_DIFF_HINT_CHARS = _EVIDENCE_SETTINGS.max_diff_hint_chars
MODEL_EVIDENCE_MAX_DOCS = _EVIDENCE_SETTINGS.max_docs
MODEL_EVIDENCE_MAX_DOC_CHARS = _EVIDENCE_SETTINGS.max_doc_chars
MODEL_EVIDENCE_MAX_WARNINGS = _EVIDENCE_SETTINGS.max_warnings
MODEL_EVIDENCE_CHUNK_SIZE = _EVIDENCE_SETTINGS.effective_chunk_size


@dataclass
class EvidenceAgentDeps:
    evidence: EvidenceBundle
    browser: BrowserToolConfig = field(default_factory=BrowserToolConfig)
    analysis_manifest: AnalysisArtifactManifest | None = None
    report_locale: str = "en"
    screenshot_policy: ScreenshotPolicy = ScreenshotPolicy.DISABLED
    screenshot_candidate_change_ids: list[str] = field(default_factory=list)
    screenshot_attempt_signatures: set[str] = field(default_factory=set)
    ui_inspection_signatures: set[str] = field(default_factory=set)
    project_id: str | None = None
    run_id: str | None = None
    workflow_task_id: str | None = None
    held_model_concurrency_key: str | None = None
    tool_calls: int = 0


def register_evidence_agent_tools(agent: Any) -> None:
    register_analysis_artifact_tools(agent)
    register_evidence_summary_tools(agent)
    register_commit_evidence_tools(agent)
    register_documentation_evidence_tools(agent)
    register_evidence_warning_tools(agent)


def register_evidence_summary_tools(agent: Any) -> None:

    @agent.tool
    def summarize_evidence(ctx: RunContext[EvidenceAgentDeps]) -> dict[str, Any]:
        """Summarize available repositories, product context and top-ranked commits."""
        ctx.deps.tool_calls += 1
        evidence = ctx.deps.evidence
        return {
            "repositories": evidence.repositories,
            "project_profile": project_profile_brief(evidence),
            "commit_count": len(evidence.commits),
            "product_context_count": len(evidence.documentation),
            "screenshot_count": len(evidence.browser_screenshots),
            "warning_count": len(evidence.warnings),
            "top_commits": [commit_brief(commit) for commit in evidence.commits[:12]],
            "product_context": [
                {
                    "name": document.name,
                    "path": document.path,
                    "preview": truncate_text(document.excerpt, 500),
                }
                for document in evidence.documentation[:MODEL_EVIDENCE_MAX_DOCS]
            ],
            "screenshots": [
                {
                    "scenario": screenshot.scenario,
                    "url": screenshot.url,
                    "path": screenshot.path,
                    "title": screenshot.title,
                    "matched_text": screenshot.matched_text,
                    "missing_text": screenshot.missing_text,
                    "console_errors": screenshot.console_errors,
                    "network_errors": screenshot.network_errors,
                    "image_hash": screenshot.image_hash,
                    "blank": screenshot.blank,
                    "ocr_text": screenshot.ocr_text,
                    "validation_status": screenshot.validation_status,
                    "validation_reasons": screenshot.validation_reasons,
                    "attempts": screenshot.attempts,
                    "notes": screenshot.notes,
                }
                for screenshot in evidence.browser_screenshots
            ],
        }

    @agent.tool
    def list_repositories(ctx: RunContext[EvidenceAgentDeps]) -> list[str]:
        """List repository identifiers or URLs included in the collected evidence."""
        ctx.deps.tool_calls += 1
        return ctx.deps.evidence.repositories


def register_commit_evidence_tools(agent: Any) -> None:
    @agent.tool
    def list_commits(
        ctx: RunContext[EvidenceAgentDeps],
        limit: int = 20,
        offset: int = 0,
        repo: str | None = None,
        min_score: int | None = None,
    ) -> dict[str, Any]:
        """List commit summaries sorted by likely user-facing relevance."""
        ctx.deps.tool_calls += 1
        commits = filtered_commits(ctx.deps.evidence, repo=repo, min_score=min_score)
        safe_offset = max(0, offset)
        safe_limit = min(max(1, limit), 50)
        page = commits[safe_offset : safe_offset + safe_limit]
        return {
            "total": len(commits),
            "offset": safe_offset,
            "limit": safe_limit,
            "commits": [commit_brief(commit) for commit in page],
        }

    @agent.tool
    def search_commits(
        ctx: RunContext[EvidenceAgentDeps],
        query: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search commit subjects, bodies, changed files and diff hints."""
        ctx.deps.tool_calls += 1
        needle = query.lower().strip()
        safe_limit = min(max(1, limit), 50)
        if not needle:
            return {"query": query, "total": 0, "commits": []}
        matches = []
        for commit in ctx.deps.evidence.commits:
            haystack = " ".join(
                [
                    commit.repo,
                    commit.short_sha,
                    commit.subject,
                    commit.body,
                    *commit.files,
                    *[hint.hint for hint in commit.diff_hints],
                ]
            ).lower()
            if needle in haystack:
                matches.append(commit)
        return {
            "query": query,
            "total": len(matches),
            "commits": [commit_brief(commit) for commit in matches[:safe_limit]],
        }

    @agent.tool
    def get_commit(ctx: RunContext[EvidenceAgentDeps], sha: str) -> dict[str, Any]:
        """Get detailed evidence for one commit by full or short SHA prefix."""
        ctx.deps.tool_calls += 1
        commit = find_commit(ctx.deps.evidence, sha)
        if commit is None:
            return {"found": False, "sha": sha}
        return {
            "found": True,
            "repo": commit.repo,
            "sha": commit.sha,
            "short_sha": commit.short_sha,
            "date": commit.date,
            "subject": commit.subject,
            "body": truncate_text(commit.body, MODEL_EVIDENCE_MAX_COMMIT_BODY_CHARS),
            "user_facing_score": commit.user_facing_score,
            "files": commit.files[:MODEL_EVIDENCE_MAX_FILES],
            "file_stats": [
                stat.model_dump() for stat in commit.file_stats[:MODEL_EVIDENCE_MAX_FILE_STATS]
            ],
            "diff_hints": [
                {
                    "file": hint.file,
                    "hint": truncate_text(hint.hint, MODEL_EVIDENCE_MAX_DIFF_HINT_CHARS),
                }
                for hint in commit.diff_hints[:MODEL_EVIDENCE_MAX_DIFF_HINTS]
            ],
        }


def register_documentation_evidence_tools(agent: Any) -> None:
    @agent.tool
    def list_documentation(ctx: RunContext[EvidenceAgentDeps]) -> list[dict[str, str]]:
        """List product context evidence items available to inspect."""
        ctx.deps.tool_calls += 1
        return [
            {
                "name": document.name,
                "path": document.path,
                "preview": truncate_text(document.excerpt, 500),
            }
            for document in ctx.deps.evidence.documentation
        ]

    @agent.tool
    def get_documentation(ctx: RunContext[EvidenceAgentDeps], name_or_path: str) -> dict[str, Any]:
        """Get one product context evidence excerpt by name or path."""
        ctx.deps.tool_calls += 1
        document = find_documentation(ctx.deps.evidence, name_or_path)
        if document is None:
            return {"found": False, "name_or_path": name_or_path}
        return {
            "found": True,
            "name": document.name,
            "path": document.path,
            "excerpt": truncate_text(document.excerpt, MODEL_EVIDENCE_MAX_DOC_CHARS),
        }

    @agent.tool
    def search_documentation(
        ctx: RunContext[EvidenceAgentDeps],
        query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Search product context excerpts for a word or phrase."""
        ctx.deps.tool_calls += 1
        needle = query.lower().strip()
        safe_limit = min(max(1, limit), 20)
        if not needle:
            return {"query": query, "total": 0, "matches": []}
        matches = [
            document
            for document in ctx.deps.evidence.documentation
            if needle in f"{document.name} {document.path} {document.excerpt}".lower()
        ]
        return {
            "query": query,
            "total": len(matches),
            "matches": [
                {
                    "name": document.name,
                    "path": document.path,
                    "preview": truncate_text(document.excerpt, 700),
                }
                for document in matches[:safe_limit]
            ],
        }


def register_evidence_warning_tools(agent: Any) -> None:
    @agent.tool
    def list_warnings(ctx: RunContext[EvidenceAgentDeps], limit: int = 20) -> dict[str, Any]:
        """List repository or product context collection warnings."""
        ctx.deps.tool_calls += 1
        safe_limit = min(max(1, limit), 100)
        return {
            "total": len(ctx.deps.evidence.warnings),
            "warnings": ctx.deps.evidence.warnings[:safe_limit],
        }


def register_analysis_artifact_tools(agent: Any) -> None:
    @agent.tool
    def list_analysis_artifacts(ctx: RunContext[EvidenceAgentDeps]) -> dict[str, Any]:
        """List durable code-analysis artifacts available to this synthesis run."""
        ctx.deps.tool_calls += 1
        manifest = ctx.deps.analysis_manifest
        return manifest.model_dump(mode="json") if manifest else {"artifacts": []}

    @agent.tool
    def read_analysis_artifact(
        ctx: RunContext[EvidenceAgentDeps],
        artifact_id: str,
    ) -> dict[str, Any]:
        """Read one bounded durable code-analysis artifact by its manifest id."""
        ctx.deps.tool_calls += 1
        manifest = ctx.deps.analysis_manifest
        artifact = (
            next((item for item in manifest.artifacts if item.id == artifact_id), None)
            if manifest
            else None
        )
        if artifact is None:
            return {"found": False, "artifact_id": artifact_id}
        path = Path(artifact.artifact_ref)
        if not path.is_file():
            return {"found": False, "artifact_id": artifact_id, "error": "artifact missing"}
        content = path.read_text(encoding="utf-8")
        limit = 16_000
        return {
            "found": True,
            "artifact_id": artifact_id,
            "path": artifact.path,
            "content": content[:limit],
            "truncated": len(content) > limit,
        }

    @agent.tool
    def analysis_coverage(ctx: RunContext[EvidenceAgentDeps]) -> dict[str, Any]:
        """Report planned, completed, failed, and missing change-analysis coverage."""
        ctx.deps.tool_calls += 1
        manifest = ctx.deps.analysis_manifest
        if manifest is None:
            return {"planned": 0, "covered": 0, "missing_paths": []}
        covered_paths = {
            f"{artifact.repository_id}:{artifact.path}" for artifact in manifest.artifacts
        }
        return {
            "planned": len(manifest.planned_paths),
            "covered": len(covered_paths),
            "completed_unit_ids": manifest.completed_unit_ids,
            "failed_unit_ids": manifest.failed_unit_ids,
            "missing_paths": [path for path in manifest.planned_paths if path not in covered_paths],
        }


def filtered_commits(
    evidence: EvidenceBundle,
    *,
    repo: str | None = None,
    min_score: int | None = None,
) -> list:
    commits = evidence.commits
    if repo:
        repo_query = repo.lower()
        commits = [commit for commit in commits if repo_query in commit.repo.lower()]
    if min_score is not None:
        commits = [commit for commit in commits if commit.user_facing_score >= min_score]
    return commits


def commit_brief(commit: CommitEvidence) -> dict[str, Any]:
    return {
        "repo": commit.repo,
        "sha": commit.short_sha,
        "date": commit.date,
        "subject": truncate_text(commit.subject, 240),
        "user_facing_score": commit.user_facing_score,
        "changed_files": len(commit.files),
        "diff_hints": [
            {
                "file": hint.file,
                "hint": truncate_text(hint.hint, 220),
            }
            for hint in commit.diff_hints[:3]
        ],
    }


def project_profile_brief(evidence: EvidenceBundle) -> dict[str, Any] | None:
    profile = evidence.project_profile
    if profile is None:
        return None
    return {
        "id": profile.id,
        "version": profile.version,
        "summary": profile.summary,
        "project_description": truncate_text(profile.project_description, 1000),
        "project_structure": profile.project_structure[:12],
        "architecture": profile.architecture[:12],
        "core_concepts": profile.core_concepts[:16],
        "agent_context": truncate_text(profile.agent_context, 3000),
        "taxonomy_version": profile.taxonomy_version,
        "categories": profile.categories[:20],
    }


def find_commit(evidence: EvidenceBundle, sha: str) -> CommitEvidence | None:
    clean_sha = sha.strip().lower()
    for commit in evidence.commits:
        if commit.sha.lower().startswith(clean_sha) or commit.short_sha.lower().startswith(
            clean_sha
        ):
            return commit
    return None


def find_documentation(
    evidence: EvidenceBundle,
    name_or_path: str,
) -> DocumentationEvidence | None:
    query = name_or_path.strip().lower()
    for document in evidence.documentation:
        if query in {document.name.lower(), document.path.lower()}:
            return document
    for document in evidence.documentation:
        if query in document.name.lower() or query in document.path.lower():
            return document
    return None


def compact_evidence_for_model(evidence: EvidenceBundle) -> tuple[EvidenceBundle, dict[str, Any]]:
    commits = [
        commit.model_copy(
            update={
                "body": truncate_text(commit.body, MODEL_EVIDENCE_MAX_COMMIT_BODY_CHARS),
                "files": commit.files[:MODEL_EVIDENCE_MAX_FILES],
                "file_stats": commit.file_stats[:MODEL_EVIDENCE_MAX_FILE_STATS],
                "diff_hints": [
                    hint.model_copy(
                        update={
                            "hint": truncate_text(
                                hint.hint,
                                MODEL_EVIDENCE_MAX_DIFF_HINT_CHARS,
                            )
                        }
                    )
                    for hint in commit.diff_hints[:MODEL_EVIDENCE_MAX_DIFF_HINTS]
                ],
            }
        )
        for commit in evidence.commits[:MODEL_EVIDENCE_MAX_COMMITS]
    ]
    documentation = [
        document.model_copy(
            update={"excerpt": truncate_text(document.excerpt, MODEL_EVIDENCE_MAX_DOC_CHARS)}
        )
        for document in evidence.documentation[:MODEL_EVIDENCE_MAX_DOCS]
    ]
    warnings = evidence.warnings[:MODEL_EVIDENCE_MAX_WARNINGS]
    compacted = evidence.model_copy(
        update={
            "commits": commits,
            "documentation": documentation,
            "warnings": warnings,
        }
    )
    prompt_json = compacted.model_dump_json(indent=2)
    stats = {
        "prompt_evidence_json_chars": len(prompt_json),
        "prompt_evidence_compacted": compacted != evidence,
        "prompt_evidence_commits_total": len(evidence.commits),
        "prompt_evidence_commits_sent": len(compacted.commits),
        "prompt_evidence_commits_omitted": max(0, len(evidence.commits) - len(compacted.commits)),
        "prompt_evidence_docs_total": len(evidence.documentation),
        "prompt_evidence_docs_sent": len(compacted.documentation),
        "prompt_evidence_warnings_total": len(evidence.warnings),
        "prompt_evidence_warnings_sent": len(compacted.warnings),
    }
    return compacted, stats


def chunk_evidence_for_model(evidence: EvidenceBundle) -> list[EvidenceBundle]:
    if not evidence.commits:
        return [compact_evidence_for_model(evidence)[0]]
    chunk_size = max(1, MODEL_EVIDENCE_CHUNK_SIZE)
    chunks = []
    for start in range(0, len(evidence.commits), chunk_size):
        raw_chunk = evidence.model_copy(
            update={"commits": evidence.commits[start : start + chunk_size]}
        )
        chunks.append(compact_evidence_for_model(raw_chunk)[0])
    return chunks


def truncate_text(value: str, max_chars: int) -> str:
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    suffix = "\n...[truncated]"
    if max_chars <= len(suffix):
        return value[:max_chars]
    return f"{value[: max_chars - len(suffix)].rstrip()}{suffix}"
