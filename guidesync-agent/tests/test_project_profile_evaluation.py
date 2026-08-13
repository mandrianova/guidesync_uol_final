from __future__ import annotations

import pytest

from guidesync_agent.schemas import (
    EvaluationAdjudicationStatus,
    EvaluationMeasurementStatus,
    ProfileClaimJudgment,
    ProfileClaimLabel,
    ProfileEvidenceAccess,
    ProfileEvidenceUse,
    ProfileGoldFact,
    ProfileGoldLabel,
    ProjectProfileEvaluationGold,
    ProjectProfileEvaluationInput,
)
from guidesync_agent.services.evaluation.project_profile import evaluate_project_profile


def test_profile_evaluation_exposes_fastapi_grounding_and_coverage_gaps() -> None:
    report = evaluate_project_profile(
        fastapi_gold(),
        ProjectProfileEvaluationInput(
            profile_id="profile-3a53e017ae",
            claims=[
                ProfileClaimJudgment(
                    id="claim-framework",
                    claim="FastAPI is a Python API framework based on type hints.",
                    label=ProfileClaimLabel.SUPPORTED_RELEVANT,
                    matched_gold_fact_ids=["fact-framework"],
                    evidence_refs=["/repositories/repo-fastapi/README.md"],
                ),
                ProfileClaimJudgment(
                    id="claim-docs-generated",
                    claim="docs contains generated documentation.",
                    label=ProfileClaimLabel.CONTRADICTED,
                    matched_gold_fact_ids=["fact-docs-source"],
                    evidence_refs=["docs/en/mkdocs.yml"],
                ),
                ProfileClaimJudgment(
                    id="claim-slim-subset",
                    claim="fastapi-slim is a minimized subset of FastAPI.",
                    label=ProfileClaimLabel.CONTRADICTED,
                    matched_gold_fact_ids=["fact-slim-migration"],
                    evidence_refs=["fastapi-slim/README.md"],
                ),
            ],
            predicted_categories=[
                "Tutorial - User Guide",
                "Advanced User Guide",
                "Deployment",
                "API Reference",
                "Security",
                "Testing",
            ],
            predicted_concepts=[
                "Path Operation Decorators",
                "Pydantic Models",
                "OpenAPI Specification",
            ],
            evidence_uses=[
                ProfileEvidenceUse(path="README.md", access=ProfileEvidenceAccess.READ),
                ProfileEvidenceUse(path="pyproject.toml", access=ProfileEvidenceAccess.READ),
                ProfileEvidenceUse(
                    path="docs/en/mkdocs.yml",
                    access=ProfileEvidenceAccess.LISTED,
                ),
                ProfileEvidenceUse(
                    path="fastapi-slim/README.md",
                    access=ProfileEvidenceAccess.LISTED,
                ),
            ],
            available_repository_paths=[
                "README.md",
                "pyproject.toml",
                "docs/en/mkdocs.yml",
                "fastapi-slim/README.md",
            ],
            comparison_categories=[
                "tutorial - user guide",
                "Advanced User Guide",
                "Deployment",
                "API Reference",
                "How To - Recipes",
            ],
        ),
    )
    metrics = {metric.name: metric for metric in report.metrics}

    assert metrics["profile_claim_precision"].value == pytest.approx(1 / 3)
    assert metrics["profile_fact_recall"].value == pytest.approx(1 / 3)
    assert metrics["profile_f1"].value == pytest.approx(1 / 3)
    assert metrics["category_precision"].value == pytest.approx(4 / 6)
    assert metrics["category_recall"].value == pytest.approx(4 / 8)
    assert metrics["concept_precision"].value == pytest.approx(2 / 3)
    assert metrics["concept_recall"].value == pytest.approx(2 / 3)
    assert metrics["profile_evidence_coverage"].value == pytest.approx(1 / 3)
    assert metrics["critical_path_coverage"].value == pytest.approx(2 / 4)
    assert metrics["category_jaccard_stability"].value == pytest.approx(4 / 7)
    assert metrics["concept_jaccard_stability"].status == (
        EvaluationMeasurementStatus.NOT_EVALUATED
    )
    assert report.unsupported_claim_ids == [
        "claim-docs-generated",
        "claim-slim-subset",
    ]
    assert report.missing_gold_fact_ids == [
        "fact-docs-source",
        "fact-slim-migration",
    ]
    assert report.missing_critical_paths == [
        "docs/en/mkdocs.yml",
        "fastapi-slim/README.md",
    ]
    assert report.listed_only_evidence_refs == [
        "docs/en/mkdocs.yml",
        "fastapi-slim/README.md",
    ]
    assert report.invalid_evidence_refs == []


def test_profile_evaluation_reports_unknown_gold_matches_and_missing_paths() -> None:
    gold = ProjectProfileEvaluationGold(
        version="profile-gold-v1",
        adjudication_status=EvaluationAdjudicationStatus.DRAFT,
        facts=[
            ProfileGoldFact(
                id="fact-1",
                statement="The project has an API.",
                evidence_refs=["README.md"],
            )
        ],
    )

    report = evaluate_project_profile(
        gold,
        ProjectProfileEvaluationInput(
            profile_id="profile-1",
            claims=[
                ProfileClaimJudgment(
                    id="claim-1",
                    claim="The project has an API.",
                    label=ProfileClaimLabel.SUPPORTED_RELEVANT,
                    matched_gold_fact_ids=["unknown-fact"],
                    evidence_refs=["missing.md#L10"],
                )
            ],
            evidence_uses=[
                ProfileEvidenceUse(path="README.md", access=ProfileEvidenceAccess.READ)
            ],
            available_repository_paths=["README.md"],
        ),
    )

    assert report.invalid_evidence_refs == ["missing.md"]
    assert report.missing_gold_fact_ids == ["fact-1"]
    assert "unknown gold fact ids" in report.findings[-1]


def fastapi_gold() -> ProjectProfileEvaluationGold:
    return ProjectProfileEvaluationGold(
        version="fastapi-profile-gold-v1",
        adjudication_status=EvaluationAdjudicationStatus.SINGLE_ANNOTATOR,
        facts=[
            ProfileGoldFact(
                id="fact-framework",
                statement="FastAPI builds Python APIs from standard type hints.",
                evidence_refs=["README.md"],
                critical=True,
            ),
            ProfileGoldFact(
                id="fact-docs-source",
                statement="docs contains documentation source and MkDocs configuration.",
                evidence_refs=["docs/en/mkdocs.yml"],
                critical=True,
            ),
            ProfileGoldFact(
                id="fact-slim-migration",
                statement="fastapi-slim is a deprecated migration package.",
                evidence_refs=["fastapi-slim/README.md"],
            ),
        ],
        categories=[
            ProfileGoldLabel(id="tutorial", value="Tutorial - User Guide"),
            ProfileGoldLabel(id="advanced", value="Advanced User Guide"),
            ProfileGoldLabel(id="deployment", value="Deployment"),
            ProfileGoldLabel(id="how-to", value="How To - Recipes"),
            ProfileGoldLabel(
                id="reference",
                value="Reference (Code API)",
                aliases=["API Reference"],
            ),
            ProfileGoldLabel(id="resources", value="Resources"),
            ProfileGoldLabel(id="about", value="About"),
            ProfileGoldLabel(id="release-notes", value="Release Notes"),
        ],
        concepts=[
            ProfileGoldLabel(
                id="path-operations",
                value="Path Operation Decorators",
            ),
            ProfileGoldLabel(id="pydantic-models", value="Pydantic Models"),
            ProfileGoldLabel(id="dependency-injection", value="Dependency Injection System"),
        ],
        critical_repository_paths=[
            "README.md",
            "pyproject.toml",
            "docs/en/mkdocs.yml",
            "fastapi-slim/README.md",
        ],
    )
