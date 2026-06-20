from __future__ import annotations

from guidesync_agent.knowledge_tagging import TaggableDocument, tag_documents, tokenize_text
from guidesync_agent.storage import score_knowledge_text


def test_tokenizer_splits_code_identifier_styles() -> None:
    tokens = set(tokenize_text("get_article ArticleManager terminal-panel.tsx"))

    assert {"get", "article", "manager", "terminal", "panel", "tsx"} <= tokens


def test_tfidf_tags_and_categories_use_identifier_terms() -> None:
    results = tag_documents(
        [
            TaggableDocument(
                id="ui",
                title="ArticleManager",
                path="src/components/ArticleManager.tsx",
                kind="file",
                text=(
                    "export function getArticlePanel() { "
                    "return <button>Article workflow</button>; }"
                ),
            ),
            TaggableDocument(
                id="storage",
                title="ArticleStore",
                path="src/storage/article_store.py",
                kind="file",
                text=(
                    "class ArticleRepository: pass\n"
                    "def get_article() -> Article: return database.fetch_article()"
                ),
            ),
        ],
        max_tags=10,
    )

    ui_result = results["ui"]
    storage_result = results["storage"]

    assert {"article", "manager", "panel"} <= set(ui_result.tags)
    assert "ui" in ui_result.categories
    assert "article" in storage_result.tags
    assert "storage" in storage_result.categories


def test_search_scoring_normalizes_identifier_styles() -> None:
    assert score_knowledge_text("ArticleManager", "article manager ui component") > 0
    assert score_knowledge_text("article manager", "ArticleManager component") > 0
