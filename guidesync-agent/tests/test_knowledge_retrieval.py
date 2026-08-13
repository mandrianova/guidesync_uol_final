from __future__ import annotations

from guidesync_agent.schemas import (
    KnowledgeAnnotationEdge,
    KnowledgeAnnotationEdgeType,
    KnowledgeAnnotationItemMetadata,
    KnowledgeAnnotationSourceType,
    KnowledgeAnnotationTargetType,
    KnowledgeChunk,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeSearchRequest,
)
from guidesync_agent.services.knowledge.retrieval import score_knowledge_search


def test_taxonomy_and_graph_signals_rank_above_lexical_only_match() -> None:
    model_section = section_node(
        "section-model-settings",
        "Model settings",
        "docs/model-settings.md",
        {
            "categories": ["model-configuration"],
            "concepts": ["configure model", "model profile"],
            "keyphrases": ["model profile"],
            "extracted_names": ["ModelSettingsPage"],
            "taxonomy_version": "profile-1:v1",
        },
    )
    lexical_section = section_node(
        "section-provider-keywords",
        "Provider keywords",
        "docs/provider-keywords.md",
        {},
    )
    chunks = [
        chunk_for(model_section, "Use this page to configure the model profile."),
        chunk_for(
            lexical_section,
            "Provider settings provider settings provider settings provider settings.",
        ),
    ]

    results = score_knowledge_search(
        KnowledgeSearchRequest(
            query="provider settings",
            components=["ModelSettingsPage"],
            workflows=["configure model"],
            keyphrases=["model profile"],
            taxonomy_version="profile-1:v1",
            limit=4,
        ),
        [model_section, lexical_section],
        chunks,
        [],
        [
            annotation_edge(
                source_id=model_section.id,
                edge_type=KnowledgeAnnotationEdgeType.DESCRIBES_COMPONENT,
                target_type=KnowledgeAnnotationTargetType.COMPONENT,
                target_value="ModelSettingsPage",
            ),
            annotation_edge(
                source_id=model_section.id,
                edge_type=KnowledgeAnnotationEdgeType.COVERS_WORKFLOW,
                target_type=KnowledgeAnnotationTargetType.WORKFLOW,
                target_value="configure model",
            ),
        ],
    )

    top = results[0]

    assert top.node.id == model_section.id
    assert top.diagnostics.score_breakdown.taxonomy > 0
    assert top.diagnostics.score_breakdown.keyphrase > 0
    assert top.diagnostics.score_breakdown.name > 0
    assert top.diagnostics.score_breakdown.graph > 0
    assert top.diagnostics.matched_terms.components == ["ModelSettingsPage"]
    assert top.diagnostics.matched_terms.workflows == ["configure model"]
    assert top.diagnostics.graph_reasons


def test_unselected_bootstrap_hint_is_not_ranked_as_controlled_category() -> None:
    billing_section = section_node(
        "section-billing",
        "Billing settings",
        "docs/billing.md",
        {
            "concepts": ["billing"],
            "needs_taxonomy_review": ["billing"],
            "taxonomy_version": "profile-1:v1",
        },
    )

    results = score_knowledge_search(
        KnowledgeSearchRequest(
            query="billing",
            categories=["billing"],
            taxonomy_version="profile-1:v1",
            limit=2,
        ),
        [billing_section],
        [chunk_for(billing_section, "Billing appears in copied legacy docs.")],
        [],
        [
            annotation_edge(
                source_id=billing_section.id,
                edge_type=KnowledgeAnnotationEdgeType.MAPS_TO_CONCEPT,
                target_type=KnowledgeAnnotationTargetType.CONCEPT,
                target_value="billing",
                needs_taxonomy_review=True,
            )
        ],
    )

    diagnostics = results[0].diagnostics

    assert diagnostics.score_breakdown.taxonomy == 0
    assert diagnostics.score_breakdown.graph <= 0.2
    assert diagnostics.matched_terms.categories == []
    assert diagnostics.warnings == [
        "candidate taxonomy terms require review and were not ranked as controlled categories"
    ]


def test_unmatched_candidate_metadata_does_not_warn() -> None:
    section = section_node(
        "section-model-settings",
        "Model settings",
        "docs/model-settings.md",
        {
            "categories": ["model-configuration"],
            "needs_taxonomy_review": ["billing"],
            "taxonomy_version": "profile-1:v1",
        },
    )

    results = score_knowledge_search(
        KnowledgeSearchRequest(
            query="model settings",
            categories=["model-configuration"],
            taxonomy_version="profile-1:v1",
            limit=2,
        ),
        [section],
        [chunk_for(section, "Configure model settings for providers.")],
        [],
        [],
    )

    assert results[0].diagnostics.score_breakdown.taxonomy > 0
    assert results[0].diagnostics.warnings == []


def test_search_results_are_deduped_by_section_node() -> None:
    section = section_node(
        "section-release-notes",
        "Release notes",
        "docs/releases.md",
        {"keyphrases": ["release notes"]},
    )

    results = score_knowledge_search(
        KnowledgeSearchRequest(query="release notes", keyphrases=["release notes"], limit=5),
        [section],
        [chunk_for(section, "Release notes explain shipped changes.")],
        [],
        [],
    )

    assert [result.node.id for result in results] == ["section-release-notes"]
    assert results[0].chunk is not None


def test_search_result_excerpt_is_bounded() -> None:
    section = section_node("section-release-notes", "Release notes", "docs/releases.md", {})
    long_text = " ".join(
        [
            *["intro"] * 120,
            "release",
            "notes",
            *["tail"] * 120,
        ]
    )

    results = score_knowledge_search(
        KnowledgeSearchRequest(query="release notes", limit=2),
        [section],
        [chunk_for(section, long_text)],
        [],
        [],
    )

    chunk_result = next(result for result in results if result.chunk is not None)

    assert len(chunk_result.matched_text) <= 320
    assert chunk_result.matched_text != long_text


def section_node(
    node_id: str,
    name: str,
    path: str,
    metadata: dict[str, object],
) -> KnowledgeNode:
    return KnowledgeNode(
        id=node_id,
        project_id="project-1",
        kind=KnowledgeNodeKind.DOC_SECTION,
        name=name,
        qualified_name=f"{path}#{name}",
        path=path,
        summary="",
        metadata=metadata,
    )


def chunk_for(node: KnowledgeNode, text: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=f"chunk-{node.id}",
        project_id=node.project_id,
        node_id=node.id,
        path=node.path,
        heading=node.name,
        text=text,
        token_count=len(text.split()),
        metadata={},
    )


def annotation_edge(
    *,
    source_id: str,
    edge_type: KnowledgeAnnotationEdgeType,
    target_type: KnowledgeAnnotationTargetType,
    target_value: str,
    needs_taxonomy_review: bool = False,
) -> KnowledgeAnnotationEdge:
    return KnowledgeAnnotationEdge(
        project_id="project-1",
        source_type=KnowledgeAnnotationSourceType.DOC_SECTION,
        source_id=source_id,
        source_path="docs/model-settings.md",
        edge_type=edge_type,
        target_type=target_type,
        target_value=target_value,
        annotation_run_id="annotation-run-1",
        metadata=KnowledgeAnnotationItemMetadata(
            needs_taxonomy_review=needs_taxonomy_review or None
        ),
    )
