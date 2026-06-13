from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Protocol

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
            title = "Custom domain guide update"
            user_facing_change = (
                "Custom domains should be documented as a workspace-level Domains workflow "
                "with DNS verification and binding steps."
            )
        elif top_commit:
            title = top_commit.subject.strip().capitalize()
            user_facing_change = top_commit.subject
        else:
            title = "Documentation update proposal"
            user_facing_change = goal
        evidence_refs = []
        if top_commit:
            evidence_refs.append(
                EvidenceReference(
                    source=f"git:{top_commit.repo}:{top_commit.short_sha}",
                    detail=top_commit.subject,
                    relevance=(
                        "Identifies the product change that may require documentation updates."
                    ),
                )
            )
            for hint in top_commit.diff_hints[:3]:
                evidence_refs.append(
                    EvidenceReference(
                        source=f"diff:{hint.file}",
                        detail=hint.hint,
                        relevance=(
                            "Visible UI or documentation hint used to ground the proposed update."
                        ),
                    )
                )
        if evidence.documentation:
            evidence_refs.append(
                EvidenceReference(
                    source=f"doc:{evidence.documentation[0].path}",
                    detail=evidence.documentation[0].excerpt[:200],
                    relevance="Existing documentation context used to avoid writing from scratch.",
                )
            )

        proposed_update = [
            f"# {title}",
            "",
            f"Audience: {audience}.",
            "",
            "## What changed",
            user_facing_change,
            "",
            "## Suggested documentation update",
            suggested_update_text(topic_text),
        ]
        if doc_excerpt:
            proposed_update.extend(
                [
                    "",
                    "## Existing documentation context",
                    doc_excerpt[:600],
                ]
            )
        if top_commit and top_commit.diff_hints:
            proposed_update.extend(["", "## Evidence-backed UI terms"])
            proposed_update.extend(f"- {hint.hint}" for hint in top_commit.diff_hints[:6])

        output = DocumentationUpdate(
            title=title,
            summary=(
                "This update proposal is generated from repository and documentation evidence. "
                "It should be reviewed before publication."
            ),
            user_facing_change=user_facing_change,
            proposed_update_markdown="\n".join(proposed_update),
            evidence_used=evidence_refs,
            reviewer_checks=[
                ReviewerCheck(
                    name="Evidence coverage",
                    status="pass" if evidence_refs else "warning",
                    notes="The proposal cites repository or documentation evidence.",
                ),
                ReviewerCheck(
                    name="Human review",
                    status="required",
                    notes="A reviewer should verify UI terminology and final publication tone.",
                ),
            ],
            risks_or_limitations=[
                (
                    "Mock provider output is deterministic and should not be treated as final "
                    "writing quality."
                ),
                "Screenshots are not yet part of this new pipeline skeleton.",
            ],
            suggested_improvements=[
                "Run the same case with hosted and local LLM providers.",
                "Add browser evidence and compare reviewer effort.",
            ],
        )
        completed = datetime.now(UTC)
        metadata = ProviderRunMetadata(
            provider=config.provider.value,
            model=config.model,
            started_at=started,
            completed_at=completed,
            latency_ms=int((time.perf_counter() - start) * 1000),
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
        started = datetime.now(UTC)
        start = time.perf_counter()
        if config.api_key_env and not os.environ.get(config.api_key_env):
            completed = datetime.now(UTC)
            metadata = ProviderRunMetadata(
                provider=config.provider.value,
                model=config.model,
                started_at=started,
                completed_at=completed,
                latency_ms=int((time.perf_counter() - start) * 1000),
                error=f"Missing API key environment variable: {config.api_key_env}",
            )
            raise RuntimeError(metadata.error)

        try:
            from pydantic_ai import Agent
        except ImportError as exc:
            raise RuntimeError("pydantic-ai is not installed. Run `uv sync`.") from exc

        instructions = (
            "You are GuideSync, an evidence-based documentation maintenance agent. "
            "Generate clear documentation updates for human review. Do not use fixed marketing "
            "phrases. Use the evidence, cite it in evidence_used, and keep uncertainty visible. "
            "Avoid raw commit hashes or source paths in user-facing prose unless they are in "
            "evidence references."
        )
        model = build_pydantic_ai_model(config)
        agent = Agent(model, output_type=DocumentationUpdate, instructions=instructions)
        prompt = (
            f"Goal: {goal}\n"
            f"Audience: {audience}\n"
            "Evidence JSON:\n"
            f"{evidence.model_dump_json(indent=2)}"
        )
        result = await agent.run(prompt)
        completed = datetime.now(UTC)
        usage = {}
        if hasattr(result, "usage"):
            try:
                usage_obj = result.usage()
                usage_dump = getattr(usage_obj, "model_dump", None)
                usage = usage_dump() if callable(usage_dump) else {}
            except Exception:  # noqa: BLE001 - best effort metadata only
                usage = {}
        metadata = ProviderRunMetadata(
            provider=config.provider.value,
            model=config.model,
            started_at=started,
            completed_at=completed,
            latency_ms=int((time.perf_counter() - start) * 1000),
            token_usage=usage,
        )
        return DocumentationUpdate.model_validate(result.output), metadata


def provider_for(config: ProviderConfig) -> ModelProvider:
    if config.provider == ProviderKind.MOCK:
        return MockProvider()
    if config.provider == ProviderKind.PYDANTIC_AI:
        return PydanticAIProvider()
    raise ValueError(f"Unsupported provider: {config.provider}")


def build_pydantic_ai_model(config: ProviderConfig):
    model_name = config.model
    if model_name.startswith("ollama:"):
        from pydantic_ai.models.ollama import OllamaModel
        from pydantic_ai.providers.ollama import OllamaProvider

        ollama_name = model_name.split(":", maxsplit=1)[1]
        if config.base_url:
            return OllamaModel(ollama_name, provider=OllamaProvider(base_url=config.base_url))
        return model_name

    if config.base_url and (
        model_name.startswith("openai:")
        or model_name.startswith("openai-chat:")
        or model_name.startswith("openai-responses:")
    ):
        from openai import AsyncOpenAI
        from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider

        api_key = os.environ.get(config.api_key_env or "", "local-not-required")
        client = AsyncOpenAI(base_url=config.base_url, api_key=api_key)
        provider = OpenAIProvider(openai_client=client)
        if model_name.startswith("openai-responses:"):
            return OpenAIResponsesModel(model_name.split(":", maxsplit=1)[1], provider=provider)
        clean_name = model_name.split(":", maxsplit=1)[1]
        return OpenAIChatModel(clean_name, provider=provider)

    return model_name


def suggested_update_text(topic_text: str) -> str:
    if "domain" in topic_text:
        return (
            "Replace the old solution-settings instructions with a guide that tells users to open "
            "the workspace Domains page, add the custom domain, publish the TXT verification "
            "record and A routing record, wait for Active status, and then bind the domain to "
            "the relevant service or published artifact."
        )
    return (
        "Update the affected guide so it explains the current workflow using the evidence "
        "listed below."
    )
