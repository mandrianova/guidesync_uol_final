from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext

from guidesync_agent.schemas import CommitEvidence, DocumentationEvidence, EvidenceBundle
from guidesync_agent.tools.browser import BrowserToolConfig

MODEL_EVIDENCE_MAX_COMMITS = int(os.environ.get("GUIDESYNC_MODEL_EVIDENCE_MAX_COMMITS", "40"))
MODEL_EVIDENCE_MAX_COMMIT_BODY_CHARS = int(
    os.environ.get("GUIDESYNC_MODEL_EVIDENCE_MAX_COMMIT_BODY_CHARS", "700")
)
MODEL_EVIDENCE_MAX_FILES = int(os.environ.get("GUIDESYNC_MODEL_EVIDENCE_MAX_FILES", "25"))
MODEL_EVIDENCE_MAX_FILE_STATS = int(os.environ.get("GUIDESYNC_MODEL_EVIDENCE_MAX_FILE_STATS", "16"))
MODEL_EVIDENCE_MAX_DIFF_HINTS = int(os.environ.get("GUIDESYNC_MODEL_EVIDENCE_MAX_DIFF_HINTS", "8"))
MODEL_EVIDENCE_MAX_DIFF_HINT_CHARS = int(
    os.environ.get("GUIDESYNC_MODEL_EVIDENCE_MAX_DIFF_HINT_CHARS", "420")
)
MODEL_EVIDENCE_MAX_DOCS = int(os.environ.get("GUIDESYNC_MODEL_EVIDENCE_MAX_DOCS", "4"))
MODEL_EVIDENCE_MAX_DOC_CHARS = int(os.environ.get("GUIDESYNC_MODEL_EVIDENCE_MAX_DOC_CHARS", "6000"))
MODEL_EVIDENCE_MAX_WARNINGS = int(os.environ.get("GUIDESYNC_MODEL_EVIDENCE_MAX_WARNINGS", "20"))
MODEL_EVIDENCE_CHUNK_SIZE = int(
    os.environ.get("GUIDESYNC_MODEL_EVIDENCE_CHUNK_SIZE", str(MODEL_EVIDENCE_MAX_COMMITS))
)


@dataclass
class EvidenceAgentDeps:
    evidence: EvidenceBundle
    browser: BrowserToolConfig = field(default_factory=BrowserToolConfig)
    tool_calls: int = 0


def register_evidence_agent_tools(agent: Any) -> None:
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

    @agent.tool
    def list_warnings(ctx: RunContext[EvidenceAgentDeps], limit: int = 20) -> dict[str, Any]:
        """List repository or product context collection warnings."""
        ctx.deps.tool_calls += 1
        safe_limit = min(max(1, limit), 100)
        return {
            "total": len(ctx.deps.evidence.warnings),
            "warnings": ctx.deps.evidence.warnings[:safe_limit],
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
        "workflows": profile.workflows[:16],
        "agent_context": truncate_text(profile.agent_context, 3000),
        "taxonomy_version": profile.taxonomy_version,
        "categories": profile.categories[:20],
        "components": profile.components[:20],
        "documentation_areas": profile.documentation_areas[:20],
        "domain_terms": profile.domain_terms[:20],
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
