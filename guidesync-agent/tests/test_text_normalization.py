from __future__ import annotations

from guidesync_agent.services.text_normalization import tokenize_identifier, tokenize_text
from guidesync_agent.storage import score_knowledge_text


def test_tokenizer_splits_code_identifier_styles() -> None:
    tokens = set(tokenize_text("get_article ArticleManager terminal-panel.tsx"))

    assert {"get", "article", "manager", "terminal", "panel", "tsx"} <= tokens


def test_identifier_tokenizer_preserves_search_terms_without_stopwords() -> None:
    assert tokenize_identifier("ArticleManager.tsx") == ["article", "manager", "tsx"]
    assert "return" not in tokenize_text("return ArticleRepositories")
    assert "article" in tokenize_text("ArticleRepositories")


def test_search_scoring_normalizes_identifier_styles() -> None:
    assert score_knowledge_text("ArticleManager", "article manager ui component") > 0
    assert score_knowledge_text("article manager", "ArticleManager component") > 0
