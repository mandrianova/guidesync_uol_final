from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import UTC, datetime
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from guidesync_agent.agent_runtime import run_release_notes_agent
from guidesync_agent.prompts import (
    local_release_notes_chunk_summary_system_prompt,
    local_release_notes_system_prompt,
)
from guidesync_agent.schemas import (
    DocumentationUpdate,
    EvidenceBundle,
    EvidenceReference,
    ProviderConfig,
    ProviderKind,
    ProviderRunMetadata,
    ReviewerCheck,
)
from guidesync_agent.tools.evidence import (
    MODEL_EVIDENCE_MAX_COMMITS,
    chunk_evidence_for_model,
    compact_evidence_for_model,
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
                    relevance=(
                        "Identifies the product change that may be user-facing."
                    ),
                )
            )
            for hint in top_commit.diff_hints[:3]:
                evidence_refs.append(
                    EvidenceReference(
                        source=f"diff:{hint.file}",
                        detail=hint.hint,
                        relevance=(
                            "Visible UI or copy hint used to ground the release note."
                        ),
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
        if config.api_key_env and not (config.api_key or os.environ.get(config.api_key_env)):
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

        result, usage = await run_release_notes_agent(
            goal=goal,
            audience=audience,
            evidence=evidence,
            config=config,
        )
        completed = datetime.now(UTC)
        metadata = ProviderRunMetadata(
            provider=config.provider.value,
            model=config.model,
            started_at=started,
            completed_at=completed,
            latency_ms=int((time.perf_counter() - start) * 1000),
            token_usage=usage,
        )
        return result, metadata


class LocalHTTPProvider:
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
        base_url = require_base_url(config)

        if len(evidence.commits) > MODEL_EVIDENCE_MAX_COMMITS:
            return await self.generate_chunked_update(
                goal=goal,
                audience=audience,
                evidence=evidence,
                config=config,
                base_url=base_url,
                started=started,
                start=start,
            )

        system_prompt = local_release_notes_system_prompt()
        compact_evidence, prompt_stats = compact_evidence_for_model(evidence)
        input_text = (
            f"Goal: {goal}\n"
            f"Audience: {audience}\n"
            "Evidence JSON:\n"
            f"{compact_evidence.model_dump_json(indent=2)}"
        )
        prompt_stats["prompt_input_chars"] = len(input_text)
        payload = {
            "model": config.model,
            "system_prompt": system_prompt,
            "input": input_text,
        }
        response = await asyncio.to_thread(
            post_local_chat,
            base_url,
            payload,
            config.timeout_seconds,
            config.api_key,
        )
        content = local_message_content(response)
        update = DocumentationUpdate.model_validate(extract_json_object(content))
        completed = datetime.now(UTC)
        stats = response.get("stats", {})
        metadata = ProviderRunMetadata(
            provider=config.provider.value,
            model=config.model,
            started_at=started,
            completed_at=completed,
            latency_ms=int((time.perf_counter() - start) * 1000),
            token_usage={**prompt_stats, **stats} if isinstance(stats, dict) else prompt_stats,
        )
        return update, metadata

    async def generate_chunked_update(
        self,
        *,
        goal: str,
        audience: str,
        evidence: EvidenceBundle,
        config: ProviderConfig,
        base_url: str,
        started: datetime,
        start: float,
    ) -> tuple[DocumentationUpdate, ProviderRunMetadata]:
        chunks = chunk_evidence_for_model(evidence)
        chunk_summaries = []
        chunk_prompt_chars = 0
        for index, chunk in enumerate(chunks, start=1):
            chunk_input = (
                f"Goal: {goal}\n"
                f"Audience: {audience}\n"
                f"Evidence chunk {index} of {len(chunks)}:\n"
                f"{chunk.model_dump_json(indent=2)}"
            )
            chunk_prompt_chars += len(chunk_input)
            response = await asyncio.to_thread(
                post_local_chat,
                base_url,
                {
                    "model": config.model,
                    "system_prompt": local_release_notes_chunk_summary_system_prompt(),
                    "input": chunk_input,
                },
                config.timeout_seconds,
                config.api_key,
            )
            summary = extract_json_object(local_message_content(response))
            summary.setdefault("chunk", index)
            chunk_summaries.append(summary)

        compact_docs, doc_stats = compact_evidence_for_model(
            evidence.model_copy(update={"commits": [], "warnings": []})
        )
        synthesis_input = (
            f"Goal: {goal}\n"
            f"Audience: {audience}\n"
            "Existing product context:\n"
            f"{compact_docs.model_dump_json(indent=2)}\n"
            "Chunk summaries JSON:\n"
            f"{json.dumps(chunk_summaries, indent=2)}\n"
            "Synthesize one coherent user-facing release notes draft. "
            "Deduplicate repeated changes, "
            "prioritize user-facing behavior, and keep uncertainty visible."
        )
        response = await asyncio.to_thread(
            post_local_chat,
            base_url,
            {
                "model": config.model,
                "system_prompt": local_release_notes_system_prompt(),
                "input": synthesis_input,
            },
            config.timeout_seconds,
            config.api_key,
        )
        content = local_message_content(response)
        update = DocumentationUpdate.model_validate(extract_json_object(content))
        completed = datetime.now(UTC)
        stats = response.get("stats", {})
        prompt_stats = {
            **doc_stats,
            "prompt_strategy": "chunked_synthesis",
            "prompt_evidence_chunks": len(chunks),
            "prompt_chunk_input_chars": chunk_prompt_chars,
            "prompt_input_chars": len(synthesis_input),
            "prompt_evidence_commits_total": len(evidence.commits),
            "prompt_evidence_commits_sent": len(evidence.commits),
            "prompt_evidence_commits_omitted": 0,
        }
        metadata = ProviderRunMetadata(
            provider=config.provider.value,
            model=config.model,
            started_at=started,
            completed_at=completed,
            latency_ms=int((time.perf_counter() - start) * 1000),
            token_usage={**prompt_stats, **stats} if isinstance(stats, dict) else prompt_stats,
        )
        return update, metadata


def provider_for(config: ProviderConfig) -> ModelProvider:
    if config.provider == ProviderKind.MOCK:
        return MockProvider()
    if config.provider == ProviderKind.PYDANTIC_AI:
        return PydanticAIProvider()
    if config.provider == ProviderKind.LOCAL_HTTP:
        return LocalHTTPProvider()
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


def require_base_url(config: ProviderConfig) -> str:
    if not config.base_url:
        raise RuntimeError("Local HTTP provider requires `base_url`.")
    return config.base_url


def post_local_chat(
    base_url: str,
    payload: dict,
    timeout_seconds: int,
    api_key: str | None = None,
) -> dict:
    url = base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(local_http_error_message(exc)) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Local model request failed: {exc}") from exc
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("Local model response must be a JSON object.")
    return parsed


def local_http_error_message(exc: HTTPError) -> str:
    body = ""
    try:
        body = exc.read().decode("utf-8")
    except Exception:  # noqa: BLE001 - HTTP body is best effort
        body = ""
    detail = ""
    if body:
        try:
            parsed = json.loads(body)
            error = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(error, dict):
                detail = str(error.get("message") or "")
            elif isinstance(parsed, dict):
                detail = str(parsed.get("message") or "")
        except json.JSONDecodeError:
            detail = body[:1000]
    if "context length" in detail.lower() or "n_keep" in detail.lower():
        return (
            "Local model context limit exceeded. The model server rejected the prompt because "
            f"it was larger than its configured context window. Details: {detail}"
        )
    suffix = f": {detail}" if detail else ""
    return f"Local model request failed: HTTP Error {exc.code} {exc.reason}{suffix}"


def local_message_content(response: dict) -> str:
    output = response.get("output")
    if isinstance(output, list):
        for item in reversed(output):
            if isinstance(item, dict) and item.get("type") == "message":
                content = item.get("content")
                if isinstance(content, str):
                    return content
    content = response.get("content") or response.get("message")
    if isinstance(content, str):
        return content
    raise RuntimeError("Local model response does not contain message content.")


def extract_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match is None:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise RuntimeError("Local model output JSON must be an object.")
    return parsed
