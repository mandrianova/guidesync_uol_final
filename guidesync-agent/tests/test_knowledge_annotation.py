from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from guidesync_agent.knowledge import build_knowledge_snapshot
from guidesync_agent.schemas import (
    KnowledgeAnnotationEdgeType,
    KnowledgeAnnotationKind,
    KnowledgeAnnotationSourceType,
    KnowledgeIndexRequest,
    KnowledgeNodeKind,
    ProjectConfig,
    ProjectProfileSnapshot,
    ProjectRepository,
    ProjectTaxonomy,
    ProjectTaxonomyAlias,
    ProjectTaxonomyBootstrapHint,
    ProjectTaxonomyBootstrapStatus,
    RepositoryInput,
)
from guidesync_agent.services.knowledge.annotation import (
    AnnotationInput,
    DeterministicNlpAnalyzer,
    DeterministicSemanticRanker,
    annotate_sources,
    preprocess_markdown,
)
from guidesync_agent.services.knowledge.annotation import analysis as annotation_analysis
from guidesync_agent.services.knowledge.annotation.constants import (
    MAX_SEMANTIC_KEYPHRASE_CANDIDATES,
)
from guidesync_agent.services.project_profile.service import (
    PROJECT_PROFILE_PROMPT_VERSION,
    analyze_project_profile,
)


def test_preprocessing_preserves_markdown_signals_without_code_block_noise() -> None:
    processed = preprocess_markdown(
        "# Billing settings\n\n"
        "Open [custom domain](/settings/domains) with ![Domain screen](domain.png).\n\n"
        "Use `ModelSettingsPage` for the model profile.\n\n"
        "```tsx\nconst noisyImplementationDetail = true\n```\n"
    )

    assert "Billing settings" in processed.headings
    assert "custom domain" in processed.link_labels
    assert "Domain screen" in processed.image_alt_texts
    assert "ModelSettingsPage" in processed.inline_code_terms
    assert "noisyImplementationDetail" not in processed.analysis_text


def test_annotation_maps_phrases_names_and_taxonomy() -> None:
    taxonomy = ProjectTaxonomy(
        version="profile-1:v1",
        categories=["model-configuration"],
        components=["ModelSettingsPage"],
        workflows=["configure model"],
        documentation_areas=["release notes"],
        domain_terms=["model profile"],
        aliases=[
            ProjectTaxonomyAlias(
                canonical="model profile",
                aliases=["model settings", "provider profile"],
            )
        ],
    )
    bundle = annotate_sources(
        [
            AnnotationInput(
                source_type=KnowledgeAnnotationSourceType.DOC_SECTION,
                source_id="section-model-settings",
                project_id="project-1",
                path="docs/model-settings.md",
                heading="Configure model",
                start_line=1,
                end_line=12,
                text=(
                    "# Configure model\n\n"
                    "The model configuration workflow uses `ModelSettingsPage` "
                    "to manage model profiles and release notes."
                ),
            )
        ],
        taxonomy=taxonomy,
        analyzer=DeterministicNlpAnalyzer(),
        semantic_ranker=DeterministicSemanticRanker(),
    )

    metadata = bundle.metadata_by_source_id["section-model-settings"]
    categories = metadata.categories
    extracted_names = metadata.extracted_names
    concepts = metadata.concepts

    assert isinstance(categories, list)
    assert isinstance(extracted_names, list)
    assert isinstance(concepts, list)

    assert bundle.annotation_runs
    assert bundle.annotations
    assert bundle.concepts
    assert bundle.annotation_edges
    assert "model-configuration" in categories
    assert "ModelSettingsPage" in extracted_names
    assert "configure model" in concepts
    assert any(
        edge.edge_type == KnowledgeAnnotationEdgeType.DESCRIBES_COMPONENT
        for edge in bundle.annotation_edges
    )


def test_semantic_keyphrase_candidates_are_bounded() -> None:
    class RecordingRanker(DeterministicSemanticRanker):
        def __init__(self) -> None:
            self.candidate_counts: list[int] = []

        def rank(self, text: str, candidates: Sequence[str]) -> dict[str, float]:
            self.candidate_counts.append(len(candidates))
            return super().rank(text, candidates)

    ranker = RecordingRanker()
    unique_terms = " ".join(f"streamingterm{index}" for index in range(180))

    annotate_sources(
        [
            AnnotationInput(
                source_type=KnowledgeAnnotationSourceType.DOC_SECTION,
                source_id="section-many-phrases",
                project_id="project-1",
                path="docs/streaming.md",
                heading="Streaming responses",
                text=f"# Streaming responses\n\n{unique_terms}",
            )
        ],
        analyzer=DeterministicNlpAnalyzer(),
        semantic_ranker=ranker,
    )

    assert ranker.candidate_counts
    assert max(ranker.candidate_counts) <= MAX_SEMANTIC_KEYPHRASE_CANDIDATES


def test_annotation_batches_semantic_ranking_without_changing_results() -> None:
    class RecordingBatchRanker(DeterministicSemanticRanker):
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []
            self.rank_calls = 0

        def rank(self, text: str, candidates: Sequence[str]) -> dict[str, float]:
            self.rank_calls += 1
            return super().rank(text, candidates)

        def rank_many(self, requests):
            self.batch_sizes.append(len(requests))
            baseline = DeterministicSemanticRanker()
            return [baseline.rank(request.text, request.candidates) for request in requests]

    sources = [
        AnnotationInput(
            source_type=KnowledgeAnnotationSourceType.DOC_SECTION,
            source_id=f"section-{index}",
            project_id="project-batch",
            path=f"docs/guide-{index}.md",
            heading="Model configuration",
            text=(
                f"# Model configuration {index}\n\n"
                "Configure the model profile for release notes."
            ),
        )
        for index in range(12)
    ]
    taxonomy = ProjectTaxonomy(
        version="profile-batch:v1",
        categories=["Model configuration", "Release notes"],
    )
    baseline = annotate_sources(
        sources,
        taxonomy=taxonomy,
        analyzer=DeterministicNlpAnalyzer(),
        semantic_ranker=DeterministicSemanticRanker(),
    )
    ranker = RecordingBatchRanker()

    batched = annotate_sources(
        sources,
        taxonomy=taxonomy,
        analyzer=DeterministicNlpAnalyzer(),
        semantic_ranker=ranker,
    )

    assert ranker.rank_calls == 0
    assert ranker.batch_sizes == [len(sources), len(sources)]
    assert batched.metadata_by_source_id == baseline.metadata_by_source_id
    assert [
        annotation.model_dump(exclude={"created_at"})
        for annotation in batched.annotations
    ] == [
        annotation.model_dump(exclude={"created_at"})
        for annotation in baseline.annotations
    ]
    assert [
        edge.model_dump(exclude={"created_at"}) for edge in batched.annotation_edges
    ] == [
        edge.model_dump(exclude={"created_at"}) for edge in baseline.annotation_edges
    ]


def test_bootstrap_hint_is_candidate_until_profile_promotes_it() -> None:
    taxonomy = ProjectTaxonomy(
        version="profile-1:v1",
        bootstrap_hints=[
            ProjectTaxonomyBootstrapHint(
                value="billing",
                status=ProjectTaxonomyBootstrapStatus.CANDIDATE,
                reason="not selected by project profile",
            )
        ],
    )

    bundle = annotate_sources(
        [
            AnnotationInput(
                source_type=KnowledgeAnnotationSourceType.DOC_SECTION,
                source_id="section-billing",
                project_id="project-1",
                path="docs/billing.md",
                heading="Billing settings",
                text="# Billing settings\n\nConfigure billing settings for the workspace.",
            )
        ],
        taxonomy=taxonomy,
        analyzer=DeterministicNlpAnalyzer(),
        semantic_ranker=DeterministicSemanticRanker(),
    )

    assert not [
        annotation
        for annotation in bundle.annotations
        if annotation.kind == KnowledgeAnnotationKind.CATEGORY
        and annotation.canonical_value == "billing"
    ]
    assert any(
        annotation.kind == KnowledgeAnnotationKind.CONCEPT
        and annotation.canonical_value == "billing"
        and annotation.metadata.needs_taxonomy_review is True
        for annotation in bundle.annotations
    )


def test_knowledge_index_creates_annotation_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "release-notes.md").write_text(
        "# Release notes\n\n"
        "The release notes explain the model configuration workflow and ModelSettingsPage.",
        encoding="utf-8",
    )

    snapshot = build_knowledge_snapshot(
        KnowledgeIndexRequest(
            project_id="project-1",
            repositories=[RepositoryInput(name="fixture", path=repo, paths=["docs"])],
            taxonomy=ProjectTaxonomy(
                version="profile-1:v1",
                categories=["model-configuration", "release-notes"],
                components=["ModelSettingsPage"],
                workflows=["model configuration"],
                documentation_areas=["release notes"],
                domain_terms=["model configuration"],
            ),
        )
    )

    section_nodes = [node for node in snapshot.nodes if node.kind == KnowledgeNodeKind.DOC_SECTION]

    assert snapshot.run.summary.annotation_runs > 0
    assert snapshot.run.summary.annotations > 0
    assert snapshot.annotation_edges
    assert section_nodes
    assert section_nodes[0].metadata["keyphrases"]
    assert "release-notes" in section_nodes[0].metadata["categories"]


def test_knowledge_index_propagates_usage_context_to_semantic_ranker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class RecordingRanker(DeterministicSemanticRanker):
        def __init__(self) -> None:
            self.contexts: list[dict[str, str | None]] = []

        def set_usage_context(self, **context: str | None) -> None:
            self.contexts.append(context)

    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "guide.md").write_text(
        "# Streaming responses\n\nValidate each JSON Lines item.",
        encoding="utf-8",
    )
    ranker = RecordingRanker()
    monkeypatch.setattr(annotation_analysis, "default_semantic_ranker", lambda _: ranker)

    build_knowledge_snapshot(
        KnowledgeIndexRequest(
            project_id="project-usage",
            repositories=[RepositoryInput(name="fixture", path=repo, paths=["docs"])],
        ),
        workflow_task_id="workflow-usage",
    )

    assert ranker.contexts
    assert all(context["project_id"] == "project-usage" for context in ranker.contexts)
    assert all(context["run_id"] is None for context in ranker.contexts)
    assert all(context["workflow_task_id"] == "workflow-usage" for context in ranker.contexts)


def test_profile_analysis_generates_documentation_categories(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)
    (repo / "src" / "ModelSettingsPage.tsx").write_text(
        "export function ModelSettingsPage() { return 'model provider settings'; }",
        encoding="utf-8",
    )
    (repo / "src" / "SubscriptionSettingsPage.tsx").write_text(
        "export function SubscriptionSettingsPage() { return 'billing invoice subscription'; }",
        encoding="utf-8",
    )
    (repo / ".env").write_text("GUIDESYNC_API_KEY=secret", encoding="utf-8")
    (repo / "docs" / "release-notes.md").write_text(
        "# Release notes\n\nDocument the model configuration workflow and knowledge base updates.",
        encoding="utf-8",
    )

    project = ProjectConfig(
        id="project-profile-taxonomy",
        name="GuideSync",
        description="Evidence-based documentation maintenance for model profiles.",
        repositories=[
            ProjectRepository(
                id="repo-primary",
                name="guidesync-agent",
                url=str(repo),
                default_branch="main",
            )
        ],
        knowledge_base_repository_id="repo-primary",
        knowledge_base_path="docs",
    )
    profile = analyze_project_profile(
        project,
        ProjectProfileSnapshot(
            project_id=project.id,
            prompt_version=PROJECT_PROFILE_PROMPT_VERSION,
        ),
    )

    assert "Model configuration" in profile.taxonomy.categories
    assert "Billing" in profile.taxonomy.categories
    assert "Release notes" in profile.taxonomy.categories
    assert profile.taxonomy.components == []
    assert profile.taxonomy.domain_terms == []
    assert profile.taxonomy.evidence_refs == []
    assert profile.model_metadata["provider"] == "pydantic_ai"
    assert profile.tool_trace_refs
    assert all(".env" not in item.path for item in profile.profile_evidence)
    assert profile.profile_evidence
