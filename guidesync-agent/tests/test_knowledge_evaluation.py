from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from guidesync_agent.schemas import (
    AnnotationEvaluationKind,
    AnnotationEvaluationSample,
    CorpusExclusionReason,
    EvaluationAdjudicationStatus,
    EvaluationMeasurementStatus,
    EvaluationMetric,
    KnowledgeCorpusEntry,
    KnowledgeCorpusGold,
    KnowledgeCorpusGoldExclusion,
)
from guidesync_agent.services.evaluation.knowledge import (
    build_knowledge_corpus_manifest,
    evaluate_annotations,
    evaluate_knowledge_corpus,
)


def test_corpus_evaluation_accounts_for_every_discovered_path(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    ignored = docs / "node_modules"
    ignored.mkdir(parents=True)
    (docs / "guide.md").write_text("indexed guide", encoding="utf-8")
    (docs / "missing.md").write_text("eligible", encoding="utf-8")
    (docs / "release-notes.md").write_text("x" * 100, encoding="utf-8")
    (docs / "logo.png").write_bytes(b"image")
    (ignored / "ignored.md").write_text("ignored", encoding="utf-8")

    manifest = build_knowledge_corpus_manifest(
        repository_root=tmp_path,
        documentation_roots=["docs"],
        indexed_paths=["docs/guide.md"],
        max_file_bytes=30,
        indexed_commit="abc123",
    )
    report = evaluate_knowledge_corpus(manifest)

    assert report.counts.discovered == 5
    assert report.counts.supported == 4
    assert report.counts.eligible == 2
    assert report.counts.indexed == 1
    assert report.counts.excluded == 4
    assert report.counts.eligible_not_indexed == 1
    assert metric(report.metrics, "eligible_index_coverage").value == pytest.approx(0.5)
    assert metric(report.metrics, "supported_document_coverage").value == pytest.approx(0.25)
    assert {entry.exclusion_reason for entry in report.excluded_entries} == {
        CorpusExclusionReason.ELIGIBLE_NOT_INDEXED,
        CorpusExclusionReason.IGNORED_PATH,
        CorpusExclusionReason.MAX_FILE_BYTES,
        CorpusExclusionReason.UNSUPPORTED_EXTENSION,
    }
    assert report.findings == ["1 eligible documentation paths were not indexed"]


def test_annotation_evaluation_reports_per_kind_micro_and_macro_scores() -> None:
    report = evaluate_annotations(
        [
            AnnotationEvaluationSample(
                id="category-1",
                kind=AnnotationEvaluationKind.CATEGORY,
                gold_values=["configuration", "api"],
                predicted_values=["Configuration", "frontend"],
                adjudication_status=EvaluationAdjudicationStatus.ADJUDICATED,
            ),
            AnnotationEvaluationSample(
                id="concept-1",
                kind=AnnotationEvaluationKind.CONCEPT,
                gold_values=["dependency injection"],
                predicted_values=["dependency injection"],
                adjudication_status=EvaluationAdjudicationStatus.ADJUDICATED,
            ),
            AnnotationEvaluationSample(
                id="concept-2",
                kind=AnnotationEvaluationKind.CONCEPT,
                gold_values=["async"],
                predicted_values=[],
                adjudication_status=EvaluationAdjudicationStatus.DRAFT,
            ),
        ]
    )

    results = {result.kind: result for result in report.kind_results}
    category = results[AnnotationEvaluationKind.CATEGORY]
    concept = results[AnnotationEvaluationKind.CONCEPT]

    assert category.counts.model_dump() == {
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 1,
        "true_negative": 0,
    }
    assert metric(category.metrics, "category_f1").value == pytest.approx(0.5)
    assert concept.counts.true_positive == 1
    assert concept.counts.false_negative == 0
    assert metric(concept.metrics, "concept_f1").value == pytest.approx(1.0)
    assert metric(report.micro_metrics, "micro_precision").value == pytest.approx(2 / 3)
    assert metric(report.micro_metrics, "micro_recall").value == pytest.approx(2 / 3)
    assert metric(report.micro_metrics, "micro_f1").value == pytest.approx(2 / 3)
    assert metric(report.macro_metrics, "macro_f1").value == pytest.approx(0.75)
    assert report.warnings == ["1 draft annotation samples were excluded from scoring"]


def test_corpus_gold_contract_detects_count_commit_and_path_drift(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("guide", encoding="utf-8")
    manifest = build_knowledge_corpus_manifest(
        repository_root=tmp_path,
        documentation_roots=["docs"],
        indexed_paths=["docs/guide.md"],
        max_file_bytes=30,
        indexed_commit="commit-1",
    )
    path_checksum = sha256(b"docs/guide.md\n").hexdigest()
    gold = KnowledgeCorpusGold(
        documentation_roots=["docs"],
        supported_extensions=[".md"],
        max_file_bytes=30,
        expected_discovered=1,
        expected_supported=1,
        expected_eligible=1,
        expected_indexed=1,
        indexed_commit="commit-1",
        supported_path_list_sha256=path_checksum,
        exclusions=[],
    )

    report = evaluate_knowledge_corpus(manifest, gold)

    assert metric(report.metrics, "corpus_count_accuracy").value == 1.0
    assert metric(report.metrics, "indexed_commit_accuracy").value == 1.0
    assert metric(report.metrics, "supported_path_checksum_accuracy").value == 1.0

    drifted = gold.model_copy(
        update={
            "expected_indexed": 0,
            "indexed_commit": "commit-2",
            "supported_path_list_sha256": "bad",
            "exclusions": [
                KnowledgeCorpusGoldExclusion(path="docs/missing.md", reason="missing")
            ],
        }
    )
    drift_report = evaluate_knowledge_corpus(manifest, drifted)

    assert metric(drift_report.metrics, "corpus_count_accuracy").value == 0.75
    assert metric(drift_report.metrics, "indexed_commit_accuracy").value == 0.0
    assert metric(drift_report.metrics, "supported_path_checksum_accuracy").value == 0.0
    assert drift_report.findings == [
        "corpus indexed mismatch: observed 1, expected 0",
        "indexed commit mismatch: observed commit-1, expected commit-2",
        "supported documentation path checksum does not match gold",
        "supported exclusion set mismatch: observed [], expected ['docs/missing.md']",
    ]


def test_corpus_entries_cannot_hide_an_eligible_indexing_miss() -> None:
    with pytest.raises(ValidationError):
        KnowledgeCorpusEntry(
            path="docs/missing.md",
            size_bytes=10,
            supported=True,
            eligible=True,
            indexed=False,
        )


def test_empty_annotation_sample_is_explicitly_undefined() -> None:
    report = evaluate_annotations([])

    assert report.kind_results == []
    assert all(
        item.status == EvaluationMeasurementStatus.UNDEFINED
        for item in [*report.micro_metrics, *report.macro_metrics]
    )


def metric(metrics: list[EvaluationMetric], name: str) -> EvaluationMetric:
    return next(item for item in metrics if item.name == name)
