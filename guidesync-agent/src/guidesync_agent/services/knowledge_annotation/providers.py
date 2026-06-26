from __future__ import annotations

import importlib
import json
import os
import urllib.request
from collections.abc import Sequence

from guidesync_agent.knowledge_tagging import tokenize_text

from .constants import (
    DEFAULT_SPACY_MODEL,
    DETERMINISTIC_ANALYZER_ID,
    DETERMINISTIC_SEMANTIC_ID,
)
from .models import NlpAnalysis, NlpAnalyzer, NlpEntity, SemanticKeyphraseRanker
from .preprocessing import deterministic_sentences, ngram_phrases, pascal_case_names
from .utils import cosine_similarity, dedupe, dedupe_display, token_overlap_score


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
        except Exception as exc:  # noqa: BLE001 - surface configured model failures as warnings
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
        SentenceTransformer = module.SentenceTransformer
        self._model = SentenceTransformer(model_name)

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
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=json.dumps({"model": self.model, "input": list(texts)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        api_key = os.environ.get("GUIDESYNC_EMBEDDING_API_KEY")
        if api_key:
            request.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        return [item["embedding"] for item in payload["data"]]


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
    model_name = os.environ.get("GUIDESYNC_SPACY_MODEL", DEFAULT_SPACY_MODEL)
    try:
        return SpacyNlpAnalyzer(model_name)
    except RuntimeError as exc:
        warning = (
            f"spaCy model-backed analyzer unavailable; degraded deterministic analyzer used: {exc}"
        )
        warnings.append(warning)
        return DeterministicNlpAnalyzer([warning])


def default_semantic_ranker(warnings: list[str]) -> SemanticKeyphraseRanker:
    endpoint = os.environ.get("GUIDESYNC_EMBEDDING_BASE_URL")
    endpoint_model = os.environ.get("GUIDESYNC_EMBEDDING_MODEL", "text-embedding")
    if endpoint:
        try:
            return LocalEmbeddingEndpointRanker(endpoint, endpoint_model)
        except RuntimeError as exc:
            warnings.append(f"local embedding endpoint unavailable: {exc}")

    transformer_model = os.environ.get("GUIDESYNC_SENTENCE_TRANSFORMER_MODEL")
    if transformer_model:
        try:
            return SentenceTransformerRanker(transformer_model)
        except RuntimeError as exc:
            warnings.append(f"sentence-transformers ranker unavailable: {exc}")

    warnings.append(
        "semantic keyphrase adapter unavailable; degraded deterministic semantic ranker used"
    )
    return DeterministicSemanticRanker()
