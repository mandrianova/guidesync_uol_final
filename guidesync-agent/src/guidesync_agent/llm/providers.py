from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any, Protocol

from guidesync_agent.agent_runtime import run_release_notes_agent
from guidesync_agent.llm.factory import pydantic_ai_generation_config
from guidesync_agent.schemas import (
    DocumentationUpdate,
    EvidenceBundle,
    EvidenceReference,
    ProviderConfig,
    ProviderKind,
    ProviderRunMetadata,
    ReviewerCheck,
)


class ModelProvider(Protocol):
    async def generate_update(
        self,
        *,
        goal: str,
        audience: str,
        evidence: EvidenceBundle,
        config: ProviderConfig,
    ) -> tuple[DocumentationUpdate, ProviderRunMetadata]: ...


class MockProvider:
    async def generate_update(
        self,
        *,
        goal: str,
        audience: str,
        evidence: EvidenceBundle,
        config: ProviderConfig,
    ) -> tuple[DocumentationUpdate, ProviderRunMetadata]:
        started = datetime.now(UTC)
        start = time.perf_counter()
        top_commit = evidence.commits[0] if evidence.commits else None
        doc_excerpt = evidence.documentation[0].excerpt if evidence.documentation else ""
        topic_text = "\n".join(
            [
                goal,
                doc_excerpt,
                *[hint.hint for commit in evidence.commits for hint in commit.diff_hints[:10]],
            ]
        ).lower()
        if "domain" in topic_text:
            title = "Custom domain management updates"
            user_facing_change = (
                "Users can manage custom domains through a workspace-level Domains workflow "
                "with DNS verification and service binding steps."
            )
        elif top_commit:
            title = top_commit.subject.strip().capitalize()
            user_facing_change = top_commit.subject
        else:
            title = "Release notes draft"
            user_facing_change = goal
        evidence_refs = []
        if top_commit:
            evidence_refs.append(
                EvidenceReference(
                    source=f"git:{top_commit.repo}:{top_commit.short_sha}",
                    detail=top_commit.subject,
                    relevance=("Identifies the product change that may be user-facing."),
                )
            )
            for hint in top_commit.diff_hints[:3]:
                evidence_refs.append(
                    EvidenceReference(
                        source=f"diff:{hint.file}",
                        detail=hint.hint,
                        relevance=("Visible UI or copy hint used to ground the release note."),
                    )
                )
        if evidence.documentation:
            evidence_refs.append(
                EvidenceReference(
                    source=f"doc:{evidence.documentation[0].path}",
                    detail=evidence.documentation[0].excerpt[:200],
                    relevance="Existing product context used to avoid inventing behavior.",
                )
            )

        release_notes = [
            f"# {title}",
            "",
            f"Audience: {audience}.",
            "",
            "## Highlights",
            user_facing_change,
            "",
            "## Details",
            suggested_release_note_text(topic_text),
        ]
        if doc_excerpt:
            release_notes.extend(
                [
                    "",
                    "## Product context to verify",
                    doc_excerpt[:600],
                ]
            )
        if top_commit and top_commit.diff_hints:
            release_notes.extend(["", "## Evidence-backed UI terms"])
            release_notes.extend(f"- {hint.hint}" for hint in top_commit.diff_hints[:6])

        output = DocumentationUpdate(
            title=title,
            summary=(
                "This release notes draft is generated from repository and product evidence. "
                "It should be reviewed before sharing with users."
            ),
            user_facing_change=user_facing_change,
            proposed_update_markdown="\n".join(release_notes),
            evidence_used=evidence_refs,
            reviewer_checks=[
                ReviewerCheck(
                    name="Evidence coverage",
                    status="pass" if evidence_refs else "warning",
                    notes="The release note cites repository or product evidence.",
                ),
                ReviewerCheck(
                    name="Human review",
                    status="required",
                    notes="A reviewer should verify user impact, UI terminology, and tone.",
                ),
            ],
            risks_or_limitations=[
                (
                    "Mock provider output is deterministic and should not be treated as final "
                    "writing quality."
                ),
                "Screenshots are only included when a browser evidence tool is available.",
            ],
            suggested_improvements=[
                "Run the same case with hosted and local LLM providers.",
                "Add browser evidence for UI-heavy changes and compare reviewer effort.",
            ],
        )
        completed = datetime.now(UTC)
        metadata = ProviderRunMetadata(
            provider=config.provider.value,
            model=config.model,
            started_at=started,
            completed_at=completed,
            latency_ms=int((time.perf_counter() - start) * 1000),
            token_usage=model_role_metadata(config),
        )
        return output, metadata


class PydanticAIProvider:
    async def generate_update(
        self,
        *,
        goal: str,
        audience: str,
        evidence: EvidenceBundle,
        config: ProviderConfig,
    ) -> tuple[DocumentationUpdate, ProviderRunMetadata]:
        runtime_config = pydantic_ai_generation_config(config)
        started = datetime.now(UTC)
        start = time.perf_counter()
        if runtime_config.api_key_env and not (
            runtime_config.api_key or os.environ.get(runtime_config.api_key_env)
        ):
            completed = datetime.now(UTC)
            metadata = ProviderRunMetadata(
                provider=runtime_config.provider.value,
                model=runtime_config.model,
                started_at=started,
                completed_at=completed,
                latency_ms=int((time.perf_counter() - start) * 1000),
                token_usage=model_role_metadata(runtime_config),
                error=f"Missing API key environment variable: {runtime_config.api_key_env}",
            )
            raise RuntimeError(metadata.error)

        result, usage = await run_release_notes_agent(
            goal=goal,
            audience=audience,
            evidence=evidence,
            config=runtime_config,
        )
        completed = datetime.now(UTC)
        metadata = ProviderRunMetadata(
            provider=runtime_config.provider.value,
            model=runtime_config.model,
            started_at=started,
            completed_at=completed,
            latency_ms=int((time.perf_counter() - start) * 1000),
            token_usage={**model_role_metadata(runtime_config), **usage},
        )
        return result, metadata


def provider_for(config: ProviderConfig) -> ModelProvider:
    if config.provider == ProviderKind.MOCK:
        return MockProvider()
    if config.provider in {ProviderKind.PYDANTIC_AI, ProviderKind.LOCAL_HTTP}:
        return PydanticAIProvider()
    raise ValueError(f"Unsupported provider: {config.provider}")


def suggested_release_note_text(topic_text: str) -> str:
    if "domain" in topic_text:
        return (
            "Teams can add and verify a custom domain from the workspace Domains area, then bind "
            "it to the relevant service or published artifact after DNS verification is active."
        )
    return (
        "Summarize the user-visible change, who it affects, and what the user can do now. "
        "Keep implementation details in evidence only."
    )


def local_response_usage(response: dict[str, Any]) -> dict[str, Any]:
    usage: dict[str, Any] = {}
    stats = response.get("stats")
    if isinstance(stats, dict):
        usage.update(stats)
    provider_usage = response.get("usage")
    if isinstance(provider_usage, dict):
        usage.update(provider_usage)
    return usage


def model_role_metadata(config: ProviderConfig) -> dict[str, Any]:
    return {
        key: value
        for key, value in config.metadata.items()
        if key
        in {
            "model_role",
            "model_bundle",
            "model_provider_family",
            "configured_provider",
            "endpoint_type",
            "supports_structured_output",
            "supports_tool_use",
            "supports_vision",
        }
    }
