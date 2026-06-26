from __future__ import annotations

from .models import (
    AnnotationBundle,
    AnnotationInput,
    NlpAnalysis,
    NlpAnalyzer,
    NlpEntity,
    PhraseCandidate,
    PreprocessedText,
    SemanticKeyphraseRanker,
    TaxonomyItem,
    TaxonomyMatch,
)
from .preprocessing import preprocess_markdown
from .providers import (
    DeterministicNlpAnalyzer,
    DeterministicSemanticRanker,
    LocalEmbeddingEndpointRanker,
    SentenceTransformerRanker,
    SpacyNlpAnalyzer,
    default_nlp_analyzer,
    default_semantic_ranker,
)
from .service import annotate_sources

__all__ = [
    "AnnotationBundle",
    "AnnotationInput",
    "DeterministicNlpAnalyzer",
    "DeterministicSemanticRanker",
    "LocalEmbeddingEndpointRanker",
    "NlpAnalysis",
    "NlpAnalyzer",
    "NlpEntity",
    "PhraseCandidate",
    "PreprocessedText",
    "SemanticKeyphraseRanker",
    "SentenceTransformerRanker",
    "SpacyNlpAnalyzer",
    "TaxonomyItem",
    "TaxonomyMatch",
    "annotate_sources",
    "default_nlp_analyzer",
    "default_semantic_ranker",
    "preprocess_markdown",
]
