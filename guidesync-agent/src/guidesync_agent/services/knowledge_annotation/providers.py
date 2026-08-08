from __future__ import annotations

import importlib
import json
import time
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError

from guidesync_agent.agent_runtime.embedding_model_usage import (
    EmbeddingModelUsageContext,
    record_embedding_model_usage,
)
from guidesync_agent.agent_runtime.model_usage import local_response_usage
from guidesync_agent.schemas.common import SemanticRankerMode
from guidesync_agent.services.text_normalization import tokenize_text
from guidesync_agent.settings import get_settings

from .constants import (
    DEFAULT_SPACY_MODEL,
    DETERMINISTIC_ANALYZER_ID,
    DETERMINISTIC_SEMANTIC_ID,
)
from .models import NlpAnalysis, NlpAnalyzer, NlpEntity, SemanticKeyphraseRanker
from .preprocessing import deterministic_sentences, ngram_phrases, pascal_case_names
from .utils import cosine_similarity, dedupe, dedupe_display, token_overlap_score

EMBEDDING_HEALTH_CHECK_TEXT = "GuideSync embedding health check"
EMBEDDING_ENDPOINT_RETRY_DELAYS_SECONDS = (0.25, 1.0)


class SpacyNlpAnalyzer:
    def __init__(self, model_name: str = DEFAULT_SPACY_MODEL) -> None:
        self.model_name = model_name
        self.method_id = f"spacy:{model_name}"
        try:
            import spacy
        except ImportError as exc:
            raise RuntimeError("spaCy is not installed") from exc
        try:
            self._nlp = spacy.load(model_name)
        except Exception as exc:
            raise RuntimeError(f"spaCy model is unavailable: {model_name}") from exc

    def analyze(self, text: str) -> NlpAnalysis:
        doc = self._nlp(text)
        lemmas: list[str] = []
        tokens: list[str] = []
        for token in doc:
            if token.is_space or token.is_punct or token.is_stop:
                continue
            token_text = token.text.strip()
            if not token_text:
                continue
            tokens.extend(tokenize_text(token_text))
            lemma = token.lemma_.strip().lower() if token.lemma_ else token_text.lower()
            if lemma and lemma != "-pron-":
                lemmas.extend(tokenize_text(lemma))

        noun_chunks: list[str] = []
        try:
            noun_chunks = [chunk.text.strip() for chunk in doc.noun_chunks if chunk.text.strip()]
        except ValueError:
            noun_chunks = []

        return NlpAnalysis(
            tokens=dedupe(tokens),
            lemmas=dedupe(lemmas or tokens),
            noun_chunks=dedupe_display(noun_chunks),
            entities=[
                NlpEntity(text=ent.text.strip(), label=ent.label_)
                for ent in doc.ents
                if ent.text.strip()
            ],
            sentences=[sent.text.strip() for sent in doc.sents if sent.text.strip()],
        )


class DeterministicNlpAnalyzer:
    method_id = DETERMINISTIC_ANALYZER_ID

    def __init__(self, warnings: Sequence[str] = ()) -> None:
        self._warnings = list(warnings)

    def analyze(self, text: str) -> NlpAnalysis:
        tokens = tokenize_text(text)
        phrases = ngram_phrases(tokens, min_n=2, max_n=4)
        entities = [NlpEntity(text=value, label="IDENTIFIER") for value in pascal_case_names(text)]
        return NlpAnalysis(
            tokens=dedupe(tokens),
            lemmas=dedupe(tokens),
            noun_chunks=phrases,
            entities=entities,
            sentences=deterministic_sentences(text),
            warnings=self._warnings,
        )


class SentenceTransformerRanker:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.method_id = f"sentence-transformers:{model_name}"
        try:
            module = importlib.import_module("sentence_transformers")
        except ImportError as exc:
            raise RuntimeError("sentence-transformers is not installed") from exc
        sentence_transformer_cls = module.SentenceTransformer
        self._model = sentence_transformer_cls(model_name)

    def rank(self, text: str, candidates: Sequence[str]) -> dict[str, float]:
        if not candidates:
            return {}
        embeddings = self._model.encode([text, *candidates], normalize_embeddings=True)
        text_vector = embeddings[0]
        return {
            candidate: float(embeddings[index + 1] @ text_vector)
            for index, candidate in enumerate(candidates)
        }


class LocalEmbeddingEndpointRanker:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.method_id = f"local-embedding-endpoint:{model}"
        self.project_id: str | None = None
        self.run_id: str | None = None
        self.workflow_task_id: str | None = None
        self.source_id: str | None = None
        self.warnings: list[str] = []

    def set_usage_context(
        self,
        *,
        project_id: str | None = None,
        run_id: str | None = None,
        workflow_task_id: str | None = None,
        source_id: str | None = None,
    ) -> None:
        self.project_id = project_id
        self.run_id = run_id
        self.workflow_task_id = workflow_task_id
        self.source_id = source_id

    def rank(self, text: str, candidates: Sequence[str]) -> dict[str, float]:
        if not candidates:
            return {}
        vectors = self._embed([text, *candidates])
        text_vector = vectors[0]
        return {
            candidate: cosine_similarity(text_vector, vectors[index + 1])
            for index, candidate in enumerate(candidates)
        }

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        try:
            payload = self._request_embeddings_with_retry(texts)
            completed_at = datetime.now(UTC)
            warning = record_embedding_model_usage(
                EmbeddingModelUsageContext(
                    model=self.model,
                    base_url=self.base_url,
                    input_count=len(texts),
                    input_chars=sum(len(text) for text in texts),
                    started_at=started_at,
                    completed_at=completed_at,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    usage=local_response_usage(payload),
                    project_id=self.project_id,
                    run_id=self.run_id,
                    workflow_task_id=self.workflow_task_id,
                    source_id=self.source_id,
                )
            )
            if warning:
                self.warnings.append(warning)
            return parse_embedding_response(payload)
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            raise RuntimeError(
                embedding_endpoint_failure_message(self.base_url, self.model, exc)
            ) from exc

    def _request_embeddings_with_retry(self, texts: Sequence[str]) -> dict[str, Any]:
        last_exc: HTTPError | URLError | TimeoutError | OSError | None = None
        for attempt_index in range(len(EMBEDDING_ENDPOINT_RETRY_DELAYS_SECONDS) + 1):
            try:
                return self._request_embeddings(texts)
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                if not is_transient_embedding_request_error(exc):
                    raise
                last_exc = exc
                if attempt_index >= len(EMBEDDING_ENDPOINT_RETRY_DELAYS_SECONDS):
                    break
                time.sleep(EMBEDDING_ENDPOINT_RETRY_DELAYS_SECONDS[attempt_index])
        if last_exc is None:
            raise RuntimeError("embedding request retry loop failed without an error")
        raise last_exc

    def _request_embeddings(self, texts: Sequence[str]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=json.dumps({"model": self.model, "input": list(texts)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        api_key = get_settings().nlp.embedding_api_key
        if api_key:
            request.add_header("Authorization", f"Bearer {api_key.get_secret_value()}")
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("embedding response must be a JSON object")
        return payload


class DeterministicSemanticRanker:
    method_id = DETERMINISTIC_SEMANTIC_ID

    def rank(self, text: str, candidates: Sequence[str]) -> dict[str, float]:
        text_terms = set(tokenize_text(text))
        scores: dict[str, float] = {}
        for candidate in candidates:
            candidate_terms = set(tokenize_text(candidate))
            scores[candidate] = token_overlap_score(text_terms, candidate_terms)
        return scores


def default_nlp_analyzer(warnings: list[str]) -> NlpAnalyzer:
    model_name = get_settings().nlp.spacy_model
    try:
        return SpacyNlpAnalyzer(model_name)
    except RuntimeError as exc:
        warning = (
            f"spaCy model-backed analyzer unavailable; degraded deterministic analyzer used: {exc}"
        )
        warnings.append(warning)
        return DeterministicNlpAnalyzer([warning])


def default_semantic_ranker(warnings: list[str]) -> SemanticKeyphraseRanker:
    settings = get_settings().nlp
    mode = configured_semantic_ranker_mode()
    if mode == SemanticRankerMode.EMBEDDING_ENDPOINT:
        endpoint = required_setting(
            settings.embedding_base_url,
            "GUIDESYNC_EMBEDDING_BASE_URL",
            "OpenAI-compatible /embeddings endpoint",
        )
        endpoint_model = required_setting(
            settings.embedding_model,
            "GUIDESYNC_EMBEDDING_MODEL",
            "embedding model",
        )
        ranker = LocalEmbeddingEndpointRanker(endpoint, endpoint_model)
        ranker.rank(EMBEDDING_HEALTH_CHECK_TEXT, [EMBEDDING_HEALTH_CHECK_TEXT])
        return ranker

    if mode == SemanticRankerMode.SENTENCE_TRANSFORMERS:
        transformer_model = required_setting(
            settings.sentence_transformer_model,
            "GUIDESYNC_SENTENCE_TRANSFORMER_MODEL",
            "sentence-transformers model",
        )
        try:
            return SentenceTransformerRanker(transformer_model)
        except RuntimeError as exc:
            raise RuntimeError(
                "GUIDESYNC_SENTENCE_TRANSFORMER_MODEL is configured, but the "
                f"sentence-transformers ranker could not be initialized: {exc}"
            ) from exc

    warnings.append(
        "GUIDESYNC_SEMANTIC_RANKER_MODE=deterministic_test; deterministic semantic "
        "ranker used for isolated tests only"
    )
    return DeterministicSemanticRanker()


def configured_semantic_ranker_mode() -> SemanticRankerMode:
    raw_mode = get_settings().nlp.semantic_ranker_mode
    try:
        return SemanticRankerMode(raw_mode.strip().lower())
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in SemanticRankerMode)
        raise RuntimeError(
            f"Unsupported GUIDESYNC_SEMANTIC_RANKER_MODE={raw_mode!r}; "
            f"expected one of: {allowed}."
        ) from exc


def required_setting(value: str | None, name: str, description: str) -> str:
    if value:
        return value
    raise RuntimeError(
        f"{name} is required for the normal GuideSync semantic ranker "
        f"({description}). Configure a real embedding provider for Docker Compose "
        "runtime. If the model server runs on the host, use "
        "http://host.docker.internal:<port>/v1 from app/worker containers. "
        "Use GUIDESYNC_SEMANTIC_RANKER_MODE=deterministic_test only for isolated tests."
    )


def parse_embedding_response(payload: object) -> list[list[float]]:
    if not isinstance(payload, dict):
        raise ValueError("embedding response must be a JSON object")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("embedding response must contain a non-empty data list")
    vectors: list[list[float]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("embedding response data items must be objects")
        embedding = item.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("embedding response items must contain embedding lists")
        vector: list[float] = []
        for value in embedding:
            if not isinstance(value, int | float):
                raise ValueError("embedding response values must be numeric")
            vector.append(float(value))
        vectors.append(vector)
    return vectors


def is_transient_embedding_request_error(exc: object) -> bool:
    return isinstance(exc, (URLError, TimeoutError, OSError)) and not isinstance(exc, HTTPError)


def embedding_endpoint_failure_message(base_url: str, model: str, exc: object) -> str:
    return (
        "GUIDESYNC_EMBEDDING_BASE_URL must point to a reachable OpenAI-compatible "
        f"/embeddings endpoint for normal GuideSync runtime. Endpoint={base_url!r}, "
        f"model={model!r}. If the model server runs on the host, use "
        "http://host.docker.internal:<port>/v1 from Docker Compose app/worker "
        "containers, not localhost. Use "
        "GUIDESYNC_SEMANTIC_RANKER_MODE=deterministic_test only for isolated tests. "
        f"Underlying error: {exc}"
    )
