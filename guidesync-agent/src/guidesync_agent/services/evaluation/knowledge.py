from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path

from guidesync_agent.knowledge import (
    documentation_file_exclusion_reason,
    is_documentation_path,
)
from guidesync_agent.schemas import (
    AnnotationEvaluationKind,
    AnnotationEvaluationKindResult,
    AnnotationEvaluationReport,
    AnnotationEvaluationSample,
    BinaryClassificationCounts,
    CorpusExclusionReason,
    EvaluationMeasurementStatus,
    EvaluationMetric,
    KnowledgeCorpusCounts,
    KnowledgeCorpusEntry,
    KnowledgeCorpusEvaluationReport,
    KnowledgeCorpusGold,
    KnowledgeCorpusManifest,
)
from guidesync_agent.services.evaluation.adjudication import (
    gold_status_findings,
    is_scorable_gold,
)
from guidesync_agent.services.evaluation.metrics import (
    f_beta_metric,
    precision_metric,
    ratio_metric,
    recall_metric,
)


def build_knowledge_corpus_manifest(
    *,
    repository_root: Path,
    documentation_roots: Sequence[str],
    indexed_paths: Sequence[str],
    max_file_bytes: int,
    indexed_commit: str | None = None,
) -> KnowledgeCorpusManifest:
    resolved_root = repository_root.resolve()
    indexed = {normalize_path(path) for path in indexed_paths}
    candidates, warnings = discover_documentation_candidates(
        resolved_root,
        documentation_roots,
    )
    entries = build_corpus_entries(resolved_root, candidates, indexed, max_file_bytes)
    discovered_paths = {entry.path for entry in entries}
    missing_indexed_paths = sorted(indexed.difference(discovered_paths))
    if missing_indexed_paths:
        warnings.append(
            f"{len(missing_indexed_paths)} indexed paths were not found under documentation roots"
        )
    return KnowledgeCorpusManifest(
        repository_root=resolved_root.as_posix(),
        documentation_roots=list(documentation_roots),
        max_file_bytes=max_file_bytes,
        indexed_commit=indexed_commit,
        entries=entries,
        warnings=warnings,
    )


def discover_documentation_candidates(
    resolved_root: Path,
    documentation_roots: Sequence[str],
) -> tuple[set[Path], list[str]]:
    candidates: set[Path] = set()
    warnings: list[str] = []
    for root_path in documentation_roots:
        documentation_root = (resolved_root / root_path).resolve()
        try:
            documentation_root.relative_to(resolved_root)
        except ValueError:
            warnings.append(f"documentation root is outside repository: {root_path}")
            continue
        if not documentation_root.exists():
            warnings.append(f"documentation root does not exist: {root_path}")
            continue
        if documentation_root.is_file() or documentation_root.is_symlink():
            candidates.add(documentation_root)
            continue
        candidates.update(
            path
            for path in documentation_root.rglob("*")
            if path.is_file() or path.is_symlink()
        )
    return candidates, warnings


def build_corpus_entries(
    resolved_root: Path,
    candidates: set[Path],
    indexed: set[str],
    max_file_bytes: int,
) -> list[KnowledgeCorpusEntry]:
    entries: list[KnowledgeCorpusEntry] = []
    for candidate in sorted(candidates):
        relative_path = candidate.relative_to(resolved_root).as_posix()
        reason = documentation_file_exclusion_reason(
            resolved_root,
            candidate,
            max_file_bytes,
        )
        eligible = reason is None
        is_indexed = relative_path in indexed
        if is_indexed and not eligible:
            raise ValueError(
                f"indexed path is ineligible under the corpus manifest rules: {relative_path}"
            )
        if eligible and not is_indexed:
            reason = CorpusExclusionReason.ELIGIBLE_NOT_INDEXED
        entries.append(
            KnowledgeCorpusEntry(
                path=relative_path,
                size_bytes=candidate.lstat().st_size,
                supported=is_documentation_path(candidate),
                eligible=eligible,
                indexed=is_indexed,
                exclusion_reason=reason,
            )
        )
    return entries


def evaluate_knowledge_corpus(
    manifest: KnowledgeCorpusManifest,
    gold: KnowledgeCorpusGold | None = None,
) -> KnowledgeCorpusEvaluationReport:
    counts = KnowledgeCorpusCounts(
        discovered=len(manifest.entries),
        supported=sum(entry.supported for entry in manifest.entries),
        eligible=sum(entry.eligible for entry in manifest.entries),
        indexed=sum(entry.indexed for entry in manifest.entries),
        excluded=sum(not entry.indexed for entry in manifest.entries),
        eligible_not_indexed=sum(
            entry.exclusion_reason == CorpusExclusionReason.ELIGIBLE_NOT_INDEXED
            for entry in manifest.entries
        ),
    )
    indexed_eligible = sum(
        entry.indexed and entry.eligible for entry in manifest.entries
    )
    indexed_supported = sum(
        entry.indexed and entry.supported for entry in manifest.entries
    )
    metrics = [
        ratio_metric(
            "eligible_index_coverage",
            indexed_eligible,
            counts.eligible,
        ),
        ratio_metric(
            "supported_document_coverage",
            indexed_supported,
            counts.supported,
        ),
    ]
    findings = list(manifest.warnings)
    if counts.eligible_not_indexed:
        findings.append(
            f"{counts.eligible_not_indexed} eligible documentation paths were not indexed"
        )
    excluded_entries = [entry for entry in manifest.entries if not entry.indexed]
    if gold is not None:
        metrics.extend(corpus_gold_metrics(manifest, counts, gold))
        findings.extend(corpus_gold_findings(manifest, counts, gold))
    return KnowledgeCorpusEvaluationReport(
        counts=counts,
        metrics=metrics,
        excluded_entries=excluded_entries,
        findings=findings,
    )


def corpus_gold_metrics(
    manifest: KnowledgeCorpusManifest,
    counts: KnowledgeCorpusCounts,
    gold: KnowledgeCorpusGold,
) -> list[EvaluationMetric]:
    observed_counts = (
        counts.discovered,
        counts.supported,
        counts.eligible,
        counts.indexed,
    )
    expected_counts = (
        gold.expected_discovered,
        gold.expected_supported,
        gold.expected_eligible,
        gold.expected_indexed,
    )
    expected_exclusions = {item.path for item in gold.exclusions}
    observed_exclusions = {
        entry.path for entry in manifest.entries if entry.supported and not entry.indexed
    }
    supported_path_checksum = corpus_supported_path_checksum(manifest)
    return [
        ratio_metric(
            "corpus_count_accuracy",
            sum(
                observed == expected
                for observed, expected in zip(
                    observed_counts,
                    expected_counts,
                    strict=True,
                )
            ),
            len(expected_counts),
        ),
        ratio_metric(
            "declared_exclusion_precision",
            len(expected_exclusions.intersection(observed_exclusions)),
            len(observed_exclusions),
        ),
        ratio_metric(
            "declared_exclusion_recall",
            len(expected_exclusions.intersection(observed_exclusions)),
            len(expected_exclusions),
        ),
        ratio_metric(
            "indexed_commit_accuracy",
            int(manifest.indexed_commit == gold.indexed_commit),
            1,
        ),
        ratio_metric(
            "supported_path_checksum_accuracy",
            int(supported_path_checksum == gold.supported_path_list_sha256),
            1,
        ),
    ]


def corpus_gold_findings(
    manifest: KnowledgeCorpusManifest,
    counts: KnowledgeCorpusCounts,
    gold: KnowledgeCorpusGold,
) -> list[str]:
    observed = {
        "discovered": counts.discovered,
        "supported": counts.supported,
        "eligible": counts.eligible,
        "indexed": counts.indexed,
    }
    expected = {
        "discovered": gold.expected_discovered,
        "supported": gold.expected_supported,
        "eligible": gold.expected_eligible,
        "indexed": gold.expected_indexed,
    }
    findings = [
        f"corpus {name} mismatch: observed {observed[name]}, expected {expected[name]}"
        for name in observed
        if observed[name] != expected[name]
    ]
    if manifest.indexed_commit != gold.indexed_commit:
        findings.append(
            "indexed commit mismatch: "
            f"observed {manifest.indexed_commit}, expected {gold.indexed_commit}"
        )
    if corpus_supported_path_checksum(manifest) != gold.supported_path_list_sha256:
        findings.append("supported documentation path checksum does not match gold")
    expected_exclusions = {item.path for item in gold.exclusions}
    observed_exclusions = {
        entry.path for entry in manifest.entries if entry.supported and not entry.indexed
    }
    if expected_exclusions != observed_exclusions:
        findings.append(
            "supported exclusion set mismatch: "
            f"observed {sorted(observed_exclusions)}, expected {sorted(expected_exclusions)}"
        )
    return findings


def corpus_supported_path_checksum(manifest: KnowledgeCorpusManifest) -> str:
    supported_paths = sorted(entry.path for entry in manifest.entries if entry.supported)
    return sha256(("\n".join(supported_paths) + "\n").encode()).hexdigest()


def evaluate_annotations(
    samples: Sequence[AnnotationEvaluationSample],
) -> AnnotationEvaluationReport:
    scorable_samples = [
        sample for sample in samples if is_scorable_gold(sample.adjudication_status)
    ]
    kind_results = [
        annotation_kind_result(kind, scorable_samples)
        for kind in AnnotationEvaluationKind
        if any(sample.kind == kind for sample in scorable_samples)
    ]
    micro_counts = sum_annotation_counts([result.counts for result in kind_results])
    micro_metrics = named_classification_metrics("micro", micro_counts)
    macro_metrics = [
        mean_metric(
            "macro_precision",
            [
                metric_for(result.metrics, f"{result.kind.value}_precision")
                for result in kind_results
            ],
        ),
        mean_metric(
            "macro_recall",
            [metric_for(result.metrics, f"{result.kind.value}_recall") for result in kind_results],
        ),
        mean_metric(
            "macro_f1",
            [metric_for(result.metrics, f"{result.kind.value}_f1") for result in kind_results],
        ),
    ]
    warnings = gold_status_findings(
        (sample.adjudication_status for sample in samples),
        label="annotation samples",
    )
    return AnnotationEvaluationReport(
        samples=list(samples),
        kind_results=kind_results,
        micro_metrics=micro_metrics,
        macro_metrics=macro_metrics,
        warnings=warnings,
    )


def annotation_kind_result(
    kind: AnnotationEvaluationKind,
    samples: Sequence[AnnotationEvaluationSample],
) -> AnnotationEvaluationKindResult:
    counts = sum_annotation_counts(
        [annotation_sample_counts(sample) for sample in samples if sample.kind == kind]
    )
    return AnnotationEvaluationKindResult(
        kind=kind,
        counts=counts,
        metrics=named_classification_metrics(kind.value, counts),
    )


def annotation_sample_counts(
    sample: AnnotationEvaluationSample,
) -> BinaryClassificationCounts:
    gold = {normalize_label(value) for value in sample.gold_values}
    predicted = {normalize_label(value) for value in sample.predicted_values}
    return BinaryClassificationCounts(
        true_positive=len(gold.intersection(predicted)),
        false_positive=len(predicted.difference(gold)),
        false_negative=len(gold.difference(predicted)),
    )


def sum_annotation_counts(
    counts: Sequence[BinaryClassificationCounts],
) -> BinaryClassificationCounts:
    return BinaryClassificationCounts(
        true_positive=sum(item.true_positive for item in counts),
        false_positive=sum(item.false_positive for item in counts),
        false_negative=sum(item.false_negative for item in counts),
        true_negative=sum(item.true_negative for item in counts),
    )


def named_classification_metrics(
    prefix: str,
    counts: BinaryClassificationCounts,
) -> list[EvaluationMetric]:
    return [
        precision_metric(counts).model_copy(update={"name": f"{prefix}_precision"}),
        recall_metric(counts).model_copy(update={"name": f"{prefix}_recall"}),
        f_beta_metric(counts).model_copy(update={"name": f"{prefix}_f1"}),
    ]


def mean_metric(name: str, metrics: Sequence[EvaluationMetric]) -> EvaluationMetric:
    measured_values = [
        metric.value
        for metric in metrics
        if metric.status == EvaluationMeasurementStatus.MEASURED
        and metric.value is not None
    ]
    return ratio_metric(name, sum(measured_values), len(measured_values))


def metric_for(metrics: Sequence[EvaluationMetric], name: str) -> EvaluationMetric:
    return next(metric for metric in metrics if metric.name == name)


def normalize_path(value: str) -> str:
    return value.strip().replace("\\", "/").removeprefix("./").lstrip("/")


def normalize_label(value: str) -> str:
    return " ".join(value.casefold().split())
