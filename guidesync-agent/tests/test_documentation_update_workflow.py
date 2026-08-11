from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from storage_test_utils import sqlite_database_url

from guidesync_agent.knowledge import build_knowledge_snapshot
from guidesync_agent.pipeline import run_guidesync
from guidesync_agent.pipeline.run import collect_and_persist_evidence
from guidesync_agent.reports import read_artifact
from guidesync_agent.schemas import (
    ChangedFileRef,
    ChangedFilesResult,
    CommitEvidence,
    DocumentationEditPlan,
    DocumentationInput,
    EvidenceBundle,
    FileChangeSummary,
    GuideSyncRunRequest,
    KnowledgeIndexRequest,
    ProjectCreate,
    ProjectProfileSnapshot,
    ProjectRepository,
    ProjectTaxonomy,
    ProviderConfig,
    ProviderKind,
    ReportConfig,
    RepositoryInput,
    RunContextSources,
)
from guidesync_agent.services.project_profile import build_project_profile_for_project
from guidesync_agent.services.repository_cache import RepositoryCacheService
from guidesync_agent.storage import (
    DatabaseProjectStore,
    create_knowledge_store,
    create_model_usage_store,
    create_run_store,
)
from guidesync_agent.workflows.documentation_update import (
    historical_analysis_refs,
    prepare_documentation_update_from_summaries,
    prepare_documentation_update_workflow,
)


def run_git(repo: Path | None, args: list[str]) -> None:
    command = ["git", *args] if repo is None else ["git", "-C", str(repo), *args]
    subprocess.run(command, check=True, capture_output=True, text=True)


def create_source_repository(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "docs").mkdir(parents=True)
    (source / "src").mkdir()
    (source / "docs" / "guide.md").write_text(
        "# Workflow guide\n\nInitial workflow documentation.\n",
        encoding="utf-8",
    )
    (source / "src" / "app.py").write_text("print('initial')\n", encoding="utf-8")
    run_git(None, ["init", str(source)])
    run_git(source, ["config", "user.email", "test@example.com"])
    run_git(source, ["config", "user.name", "GuideSync Test"])
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Initial workflow docs"])
    (source / "docs" / "guide.md").write_text(
        "# Workflow guide\n\nInitial workflow documentation.\n\nDocument changed-file manifests.\n",
        encoding="utf-8",
    )
    (source / "src" / "app.py").write_text(
        "print('initial')\nprint('changed file manifest')\n",
        encoding="utf-8",
    )
    run_git(source, ["add", "."])
    run_git(source, ["commit", "-m", "Add changed-file manifest docs"])
    run_git(source, ["branch", "-M", "main"])
    return source


def test_historical_analysis_uses_the_evidence_commit_range() -> None:
    repository = RepositoryInput(
        name="starlight",
        until="2025-04-08",
    )
    evidence = EvidenceBundle(
        commits=[
            CommitEvidence(
                repo="starlight",
                sha="newest",
                short_sha="newest",
                date="2025-04-08",
                subject="Newer selected change",
            ),
            CommitEvidence(
                repo="starlight",
                sha="oldest",
                short_sha="oldest",
                date="2025-04-07",
                subject="Older selected change",
            ),
        ]
    )

    assert historical_analysis_refs(repository, evidence) == ("oldest^", "newest")


def test_historical_analysis_uses_selected_branch_evidence_without_until() -> None:
    repository = RepositoryInput(
        name="starlight [feature/headless]",
        ref="main",
        since=None,
        branches=["feature/headless"],
    )
    evidence = EvidenceBundle(
        commits=[
            CommitEvidence(
                repo="starlight [feature/headless]",
                sha="branch-head",
                short_sha="branch-he",
                date="2026-08-11",
                subject="Finish branch feature",
            ),
            CommitEvidence(
                repo="starlight [feature/headless]",
                sha="branch-first",
                short_sha="branch-fi",
                date="2026-08-10",
                subject="Start branch feature",
            ),
        ]
    )

    assert historical_analysis_refs(repository, evidence) == (
        "branch-first^",
        "branch-head",
    )


def test_empty_bounded_period_produces_an_empty_ref_range() -> None:
    repository = RepositoryInput(
        name="starlight",
        ref="main",
        until="2026-08-11",
        branches=["main"],
    )

    assert historical_analysis_refs(repository, EvidenceBundle()) == (
        "origin/main",
        "origin/main",
    )


def test_no_context_sources_skip_profile_retrieval_and_edit_planning(tmp_path: Path) -> None:
    request = GuideSyncRunRequest(
        run_id="run-no-context",
        goal="Draft release guidance.",
        repositories=[
            RepositoryInput(
                name="fixture",
                project_id="project-1",
                repository_id="repo-1",
            )
        ],
        report=ReportConfig(output_dir=tmp_path / "run-output"),
        context_sources=RunContextSources(
            project_profile=False,
            knowledge_base=False,
            edit_planning=False,
        ),
    )

    context = prepare_documentation_update_from_summaries(request, [], [])

    assert context.project_profile is None
    assert context.retrieved_docs == []
    assert context.edit_plan is None
    assert "project-profile.json" not in context.artifacts
    assert "retrieved-docs.json" in context.artifacts
    manifest = json.loads(Path(context.artifacts["context-sources.json"]).read_text())
    assert manifest["condition_id"] == "B3"
    assert manifest["knowledge_base"] == {"enabled": False, "retrieved": []}
    assert len(manifest["checksum"]) == 64


def test_no_knowledge_condition_withholds_configured_documentation(monkeypatch) -> None:
    captured_documentation = None

    def capture_evidence(_repositories, documentation):
        nonlocal captured_documentation
        captured_documentation = documentation
        return EvidenceBundle()

    monkeypatch.setattr("guidesync_agent.pipeline.run.collect_evidence", capture_evidence)
    request = GuideSyncRunRequest(
        run_id="run-no-knowledge-documents",
        goal="Draft release guidance.",
        repositories=[RepositoryInput(name="fixture")],
        documentation=[
            DocumentationInput(
                name="Existing guide",
                content="This content must be withheld from the no-KB condition.",
            )
        ],
        context_sources=RunContextSources(knowledge_base=False),
    )
    collect_and_persist_evidence(request, create_run_store())

    assert captured_documentation == []


def test_g_k_keeps_edit_planning_with_an_empty_knowledge_candidate_set(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured_paths: list[str] | None = None

    def fail_search(_request):
        raise AssertionError("G-K must not query the knowledge base")

    def plan_without_knowledge(_project_id, planning_context, **_kwargs):
        nonlocal captured_paths
        captured_paths = planning_context.candidate_document_paths
        return DocumentationEditPlan(
            id="plan-g-k",
            target_path="docs/release.md",
            docs_path="docs",
        )

    monkeypatch.setattr(
        "guidesync_agent.workflows.documentation_update.search_knowledge_base",
        fail_search,
    )
    monkeypatch.setattr(
        "guidesync_agent.workflows.documentation_update.plan_documentation_edit",
        plan_without_knowledge,
    )
    monkeypatch.setattr(
        "guidesync_agent.workflows.documentation_update.project_profile_for_request",
        lambda _request, project_id: ProjectProfileSnapshot(
            id="profile-g-k",
            project_id=project_id,
            prompt_version="test-profile",
            taxonomy=ProjectTaxonomy(version="taxonomy-g-k"),
        ),
    )
    request = GuideSyncRunRequest(
        run_id="run-g-k",
        goal="Draft release guidance.",
        repositories=[
            RepositoryInput(
                name="fixture",
                project_id="project-1",
                repository_id="repo-1",
            )
        ],
        report=ReportConfig(output_dir=tmp_path / "run-output"),
        context_sources=RunContextSources(
            project_profile=True,
            knowledge_base=False,
            edit_planning=True,
        ),
    )

    context = prepare_documentation_update_from_summaries(request, [], [])
    manifest = json.loads(Path(context.artifacts["context-sources.json"]).read_text())

    assert captured_paths == []
    assert context.project_profile is not None
    assert context.project_profile.id == "profile-g-k"
    assert context.edit_plan is not None and context.edit_plan.id == "plan-g-k"
    assert manifest["condition_id"] == "G-K"
    assert manifest["project_profile"]["snapshot_id"] == "profile-g-k"
    assert manifest["edit_planning"]["enabled"] is True


def test_g_k_disables_knowledge_during_synchronous_change_analysis(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured_contexts = []
    profile = ProjectProfileSnapshot(
        id="profile-g-k",
        project_id="project-1",
        prompt_version="test-profile",
        taxonomy=ProjectTaxonomy(version="taxonomy-g-k"),
    )
    monkeypatch.setattr(
        "guidesync_agent.workflows.documentation_update.project_profile_for_request",
        lambda _request, _project_id: profile,
    )
    monkeypatch.setattr(
        "guidesync_agent.workflows.documentation_update.list_changed_files",
        lambda *_args, **_kwargs: ChangedFilesResult(
            repository_id="repo-1",
            head_ref="HEAD",
            files=[ChangedFileRef(path="src/menu.ts", status="modified")],
        ),
    )

    def capture_change_context(change_context, changed_file):
        captured_contexts.append(change_context)
        return FileChangeSummary(
            repository_id=change_context.repository_id,
            path=changed_file.path,
            status=changed_file.status,
            technical_summary="Menu changed.",
            product_impact="Mobile navigation changed.",
        )

    monkeypatch.setattr(
        "guidesync_agent.workflows.documentation_update.summarize_changed_file",
        capture_change_context,
    )
    request = GuideSyncRunRequest(
        run_id="run-g-k-synchronous",
        goal="Draft release guidance.",
        repositories=[
            RepositoryInput(
                name="fixture",
                project_id="project-1",
                repository_id="repo-1",
            )
        ],
        report=ReportConfig(output_dir=tmp_path / "run-output"),
        context_sources=RunContextSources(
            project_profile=True,
            knowledge_base=False,
            edit_planning=False,
        ),
    )

    context = prepare_documentation_update_workflow(request)

    assert len(captured_contexts) == 1
    assert captured_contexts[0].project_profile == profile
    assert captured_contexts[0].knowledge_context_enabled is False
    assert context.project_profile == profile


def test_historical_analysis_does_not_treat_relevance_order_as_history(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "cache"))
    source = create_source_repository(tmp_path)
    commits = subprocess.run(
        ["git", "-C", str(source), "log", "--format=%H"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    newest, oldest = commits
    cache_root = RepositoryCacheService().cache_path("project-range", "repo-range")
    cache_root.parent.mkdir(parents=True)
    run_git(None, ["clone", str(source), str(cache_root)])
    repository = RepositoryInput(
        name="fixture",
        project_id="project-range",
        repository_id="repo-range",
        url=str(source),
        until="2026-08-10",
    )
    evidence = EvidenceBundle(
        commits=[
            CommitEvidence(
                repo="fixture",
                sha=oldest,
                short_sha=oldest[:8],
                date="2026-08-10",
                subject="Older but more relevant change",
                user_facing_score=10,
            ),
            CommitEvidence(
                repo="fixture",
                sha=newest,
                short_sha=newest[:8],
                date="2026-08-10",
                subject="Newer change",
                user_facing_score=1,
            ),
        ]
    )

    assert historical_analysis_refs(repository, evidence) == (
        "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
        newest,
    )


def test_unresolvable_oldest_commit_does_not_masquerade_as_a_root_commit(
    tmp_path: Path,
) -> None:
    source = create_source_repository(tmp_path)
    repository = RepositoryInput(
        name="fixture",
        local_path=source,
        until="2026-08-10",
    )
    evidence = EvidenceBundle(
        commits=[
            CommitEvidence(
                repo="fixture",
                sha="missing-commit",
                short_sha="missing",
                date="2026-08-10",
                subject="Unavailable commit",
            )
        ]
    )

    assert historical_analysis_refs(repository, evidence) == (
        "missing-commit^",
        "missing-commit",
    )


def test_run_guidesync_writes_documentation_workflow_artifacts(  # noqa: PLR0915
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = sqlite_database_url(tmp_path / "workflow.db")
    monkeypatch.setenv("GUIDESYNC_DATABASE_URL", database_url)
    monkeypatch.setenv("GUIDESYNC_REPOSITORY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GUIDESYNC_PROJECT_PROFILE_OUTPUT_DIR", str(tmp_path / "profiles"))
    source = create_source_repository(tmp_path)
    project = DatabaseProjectStore(database_url).save(
        ProjectCreate(
            name="Workflow project",
            description="Tests documentation update workflow context.",
            knowledge_base_path="docs/",
            repositories=[
                ProjectRepository(
                    id="repo-workflow",
                    name="fixture",
                    url=str(source),
                    default_branch="main",
                    analysis_paths=["docs", "src"],
                )
            ],
        )
    )
    profile = build_project_profile_for_project(project, reason="test")
    snapshot = build_knowledge_snapshot(
        KnowledgeIndexRequest(
            project_id=project.id,
            repositories=[
                RepositoryInput(
                    name="fixture",
                    project_id=project.id,
                    repository_id="repo-workflow",
                    url=str(source),
                    ref="main",
                    paths=["docs"],
                )
            ],
        )
    )
    create_knowledge_store().save_snapshot(snapshot)
    request = GuideSyncRunRequest(
        run_id=f"{project.id}-workflow",
        goal="Document changed-file manifests for workflow guide.",
        provider=ProviderConfig(provider=ProviderKind.MOCK, model="mock:deterministic"),
        repositories=[
            RepositoryInput(
                name="fixture",
                project_id=project.id,
                repository_id="repo-workflow",
                url=str(source),
                branches=["main"],
                paths=["docs", "src"],
            )
        ],
        report=ReportConfig(output_dir=tmp_path / "run-output"),
        project_profile_snapshot_id=profile.id,
    )

    result = asyncio.run(run_guidesync(request))

    assert result.status == "completed"
    assert {
        "changed-files.json",
        "context-sources.json",
        "documentation-edit.json",
        "documentation-edit-plan.json",
        "documentation.patch",
        "file-summaries.json",
        "knowledge-access-manifest.json",
        "project-profile.json",
        "retrieved-docs.json",
    } <= set(result.artifacts)
    changed_files = json.loads(read_artifact(result.artifacts["changed-files.json"]).body)
    file_summaries = json.loads(read_artifact(result.artifacts["file-summaries.json"]).body)
    retrieved_docs = json.loads(read_artifact(result.artifacts["retrieved-docs.json"]).body)
    access_manifest = json.loads(
        read_artifact(result.artifacts["knowledge-access-manifest.json"]).body
    )
    stored_profile = json.loads(read_artifact(result.artifacts["project-profile.json"]).body)
    documentation_edit = json.loads(read_artifact(result.artifacts["documentation-edit.json"]).body)
    markdown_report = read_artifact(result.artifacts["technical-report.md"]).body.decode()
    json_report = json.loads(read_artifact(result.artifacts["run.json"]).body)

    assert {item["path"] for item in changed_files["files"]} == {
        "docs/guide.md",
        "src/app.py",
    }
    summaries = file_summaries["summaries"]
    assert {item["path"] for item in summaries} == {"docs/guide.md", "src/app.py"}
    assert all(Path(item["artifact_uri"]).exists() for item in summaries)
    assert all("diff" not in item and "content" not in item for item in summaries)
    assert all(item["analysis_artifact"]["prompt_version"] for item in summaries)
    assert all(item["analysis_artifact"]["evidence_refs"] for item in summaries)
    assert all(item["annotation_run_id"] for item in summaries)
    assert any(
        item["path"] == "src/app.py" and item["needs_main_agent_review"] is True
        for item in summaries
    )
    assert retrieved_docs["results"]
    assert access_manifest["selected_count"] > 0
    assert access_manifest["read_count"] == 0
    assert access_manifest["cited_count"] == 0
    assert all(
        item["used_for_planning"] == (item["path"] == documentation_edit["target_path"])
        for item in access_manifest["items"]
    )
    assert not any(item["used_for_generation"] for item in access_manifest["items"])
    assert stored_profile["id"] == profile.id
    assert stored_profile["agent_context"]
    assert result.evidence.project_profile is not None
    assert result.evidence.project_profile.id == profile.id
    assert result.evidence.project_profile.agent_context
    assert documentation_edit["status"] == "committed"
    assert documentation_edit["commit_sha"]
    assert documentation_edit["changed_docs"] == ["docs/guide.md"]
    assert documentation_edit["edit_plan_artifact_uri"]
    assert read_artifact(result.artifacts["documentation-edit-plan.json"]).body
    assert "documentation.patch" in markdown_report
    assert "file-summaries.json" in markdown_report
    assert "documentation.patch" in json_report["artifacts"]
    assert "file-summaries.json" in json_report["artifacts"]
    assert result.update is not None
    assert result.update.documentation_edit is not None
    assert result.update.documentation_edit.commit_sha
    assert "docs/guide.md" in result.update.proposed_update_markdown
    usage_summary = create_model_usage_store().summarize_run(request.run_id)
    assert usage_summary.calls == 1
    assert usage_summary.by_role[0].key == "orchestrator"
    assert any(
        reference.source.startswith("doc-change:") for reference in result.update.evidence_used
    )
    assert not any(
        reference.source.startswith("knowledge:") for reference in result.update.evidence_used
    )
