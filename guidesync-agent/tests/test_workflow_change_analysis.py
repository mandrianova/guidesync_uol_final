import asyncio
from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

from guidesync_agent.agent_runtime import change_analysis_orchestrator as orchestrator_runtime
from guidesync_agent.schemas import (
    ChangeAnalysisCheckpoint,
    ChangeAnalysisCoverage,
    ChangeAnalysisCoverageDisposition,
    ChangeAnalysisInventory,
    ChangeAnalysisInventoryItem,
    ChangeAnalysisInventoryItemKind,
    ChangeAnalysisPlanWorkflowInput,
    ChangeAnalysisPlanWorkflowResult,
    ChangeAnalysisWorkflowInput,
    ChangeAnalysisWorkflowResult,
    ChangeSynthesisWorkflowInput,
    CommitEvidence,
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ProjectWorkflowTask,
    ProjectWorkflowTaskKind,
    ProjectWorkflowTaskStatus,
    ReleaseChangeConfidence,
    ReleaseChangeFinding,
    ReleaseChangeKind,
    RepositoryInput,
)
from guidesync_agent.services import workflow_change_analysis, workflow_change_inventory
from guidesync_agent.services.workflow_change_analysis import build_analysis_manifest
from guidesync_agent.tools import change_analysis_orchestrator
from guidesync_agent.tools.change_analysis_orchestrator import (
    ChangeAnalysisOrchestratorDeps,
    register_change_analysis_orchestrator_tools,
)


def semantic_analysis_fixture() -> tuple[ChangeAnalysisInventory, ChangeAnalysisCheckpoint]:
    inventory = ChangeAnalysisInventory(
        run_id="run-1",
        items=[
            ChangeAnalysisInventoryItem(
                key="path:repo-1:src/app.py",
                kind=ChangeAnalysisInventoryItemKind.PATH,
                repository_id="repo-1",
                summary="M src/app.py",
                path="src/app.py",
                status="M",
                base_ref="base",
                head_ref="head",
            )
        ],
    )
    finding = ReleaseChangeFinding(
        id="streaming-response",
        title="Stream response rows",
        kind=ReleaseChangeKind.FEATURE,
        technical_summary="Routing now streams rows incrementally.",
        user_impact="Developers can return a streamed response.",
        coverage_keys=["path:repo-1:src/app.py"],
        evidence_refs=["diff:repo-1:src/app.py:base:head"],
        documentation_search_intents=["streaming response"],
        artifact_ref="/tmp/release-change-findings.json",
    )
    checkpoint = ChangeAnalysisCheckpoint(
        findings=[finding],
        coverage=[
            ChangeAnalysisCoverage(
                key="path:repo-1:src/app.py",
                disposition=ChangeAnalysisCoverageDisposition.FINDING,
                finding_id=finding.id,
            )
        ],
        completed=True,
    )
    return inventory, checkpoint


def test_analysis_manifest_carries_semantic_finding() -> None:
    inventory, checkpoint = semantic_analysis_fixture()
    analysis_task = ProjectWorkflowTask(
        id="analysis-1",
        project_id="project-1",
        kind=ProjectWorkflowTaskKind.CHANGE_ANALYSIS,
        status=ProjectWorkflowTaskStatus.COMPLETED,
        input=ChangeAnalysisWorkflowInput(run_id="run-1", plan_task_id="plan-1"),
        result=ChangeAnalysisWorkflowResult(
            inventory=inventory,
            checkpoint=checkpoint,
        ),
    )

    manifest = build_analysis_manifest(
        ChangeSynthesisWorkflowInput(
            run_id="run-1",
            plan_task_id="plan-1",
            analysis_task_id=analysis_task.id,
        ),
        analysis_task,
    )

    assert manifest.completed_unit_ids == [analysis_task.id]
    assert manifest.findings[0].id == "streaming-response"
    assert manifest.coverage[0].finding_id == "streaming-response"
    assert manifest.artifacts[0].digest.technical_summary.startswith("Routing now")


def test_analysis_plan_enqueues_one_analysis_and_one_synthesis(monkeypatch, tmp_path) -> None:
    request = GuideSyncRunRequest(run_id="run-1", goal="Draft documentation.")
    request.report.output_dir = tmp_path
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="running",
        request=request,
        evidence=EvidenceBundle(),
    )
    parent = ProjectWorkflowTask(
        project_id="project-1",
        kind=ProjectWorkflowTaskKind.CHANGE_ANALYSIS_PLAN,
        input=ChangeAnalysisPlanWorkflowInput(run_id=run.run_id),
    )
    inventory, _ = semantic_analysis_fixture()

    class WorkflowStore:
        def __init__(self) -> None:
            self.enqueued = []

        def enqueue(self, task):
            self.enqueued.append(task)
            return task

    store = WorkflowStore()
    monkeypatch.setattr(workflow_change_analysis, "require_workflow_run", lambda _: run)
    monkeypatch.setattr(workflow_change_analysis, "mark_analysis_run_started", lambda _: run)
    monkeypatch.setattr(
        workflow_change_analysis,
        "collect_change_analysis_inventory",
        lambda _: inventory,
    )
    monkeypatch.setattr(
        workflow_change_analysis,
        "write_workflow_artifact",
        lambda *args, **kwargs: "/tmp/change-analysis-plan.json",
    )
    monkeypatch.setattr(
        workflow_change_analysis,
        "create_project_workflow_store",
        lambda: store,
    )

    completed = workflow_change_analysis.execute_change_analysis_plan(parent)
    result = ChangeAnalysisPlanWorkflowResult.model_validate(completed.result)

    assert [task.kind for task in store.enqueued] == [
        ProjectWorkflowTaskKind.CHANGE_ANALYSIS,
        ProjectWorkflowTaskKind.CHANGE_SYNTHESIS,
    ]
    assert store.enqueued[1].depends_on_task_ids == [store.enqueued[0].id]
    assert result.analysis_task_id == store.enqueued[0].id
    assert result.refresh_task_id is None


def test_analysis_inventory_uses_historical_evidence_refs(monkeypatch) -> None:
    repository = RepositoryInput(
        name="starlight",
        project_id="project-1",
        repository_id="repo-1",
        until="2025-04-08",
    )
    request = GuideSyncRunRequest(
        run_id="run-historical",
        goal="Document the selected historical change.",
        repositories=[repository],
    )
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="running",
        request=request,
        evidence=EvidenceBundle(),
    )
    evidence = EvidenceBundle(
        commits=[
            CommitEvidence(
                repo="starlight",
                sha="selected-sha",
                short_sha="selected",
                date="2025-04-07",
                subject="Selected historical change",
                files=["MobileMenuToggle.astro"],
            )
        ]
    )
    observed = {}

    monkeypatch.setattr(workflow_change_inventory, "collect_evidence", lambda *_: evidence)
    monkeypatch.setattr(
        workflow_change_inventory,
        "create_run_store",
        lambda: SimpleNamespace(save=lambda result: observed.update(saved=result)),
    )

    monkeypatch.setattr(
        workflow_change_inventory,
        "list_changed_files",
        lambda *_args, **_kwargs: pytest.fail(
            "Path inventory must not duplicate available commit inventory."
        ),
    )

    inventory = workflow_change_inventory.collect_change_analysis_inventory(run)

    assert observed["saved"].evidence.commits == evidence.commits
    assert [item.kind for item in inventory.items] == [
        ChangeAnalysisInventoryItemKind.COMMIT
    ]
    assert inventory.items[0].base_ref == "selected-sha^"
    assert inventory.items[0].head_ref == "selected-sha"
    assert inventory.items[0].related_paths == ["MobileMenuToggle.astro"]


def test_analysis_inventory_falls_back_to_paths_without_commits(monkeypatch) -> None:
    repository = RepositoryInput(
        name="empty-history",
        project_id="project-1",
        repository_id="repo-1",
    )
    request = GuideSyncRunRequest(
        run_id="run-path-fallback",
        goal="Document working tree changes.",
        repositories=[repository],
    )
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="running",
        request=request,
        evidence=EvidenceBundle(),
    )
    monkeypatch.setattr(
        workflow_change_inventory,
        "collect_evidence",
        lambda *_: EvidenceBundle(),
    )
    monkeypatch.setattr(
        workflow_change_inventory,
        "create_run_store",
        lambda: SimpleNamespace(save=lambda _result: None),
    )
    monkeypatch.setattr(
        workflow_change_inventory,
        "list_changed_files",
        lambda *_args, **_kwargs: SimpleNamespace(
            error=None,
            files=[SimpleNamespace(path="src/app.py", status="A")],
            base_ref="base",
            head_ref="head",
        ),
    )

    inventory = workflow_change_inventory.collect_change_analysis_inventory(run)

    assert len(inventory.items) == 1
    assert inventory.items[0].kind is ChangeAnalysisInventoryItemKind.PATH
    assert inventory.items[0].path == "src/app.py"
    assert inventory.items[0].status == "A"


def test_changed_files_are_derived_from_commit_related_paths() -> None:
    inventory = ChangeAnalysisInventory(
        run_id="run-1",
        items=[
            ChangeAnalysisInventoryItem(
                key="commit:repo-1:abc123",
                kind=ChangeAnalysisInventoryItemKind.COMMIT,
                repository_id="repo-1",
                summary="Add streaming support",
                commit_sha="abc123",
                related_paths=["src/app.py", "tests/test_app.py", "src/app.py"],
                base_ref="abc123^",
                head_ref="abc123",
            )
        ],
    )

    assert workflow_change_analysis.inventory_changed_files(inventory) == [
        {"repository_id": "repo-1", "path": "src/app.py", "status": "M"},
        {"repository_id": "repo-1", "path": "tests/test_app.py", "status": "M"},
    ]


def test_save_finding_persists_checkpoint(monkeypatch) -> None:
    inventory, _ = semantic_analysis_fixture()
    task = ProjectWorkflowTask(
        id="analysis-1",
        project_id="project-1",
        kind=ProjectWorkflowTaskKind.CHANGE_ANALYSIS,
        status=ProjectWorkflowTaskStatus.RUNNING,
        input=ChangeAnalysisWorkflowInput(run_id="run-1", plan_task_id="plan-1"),
    )

    class WorkflowStore:
        def __init__(self) -> None:
            self.task = task

        def get(self, _task_id):
            return self.task

        def save(self, saved):
            self.task = saved
            return saved

    class FakeAgent:
        def __init__(self) -> None:
            self.tools = {}

        def tool(self, function=None, **_kwargs):
            def register(candidate):
                self.tools[candidate.__name__] = candidate
                return candidate

            return register(function) if function is not None else register

    store = WorkflowStore()
    monkeypatch.setattr(
        change_analysis_orchestrator,
        "create_project_workflow_store",
        lambda: store,
    )
    agent = FakeAgent()
    register_change_analysis_orchestrator_tools(agent)
    deps = ChangeAnalysisOrchestratorDeps(
        project_id="project-1",
        run_id="run-1",
        workflow_task_id=task.id,
        inventory=inventory,
        checkpoint=ChangeAnalysisCheckpoint(),
        audience="developers",
    )

    result = agent.tools["save_change_artifact"](
        SimpleNamespace(deps=deps),
        "streaming-response",
        "Stream response rows",
        " Internal ",
        "Routing now streams rows incrementally.",
        "Developers can return a streamed response.",
        ["path:repo-1:src/app.py"],
        ["diff:repo-1:src/app.py:base:head"],
        confidence=" HIGH ",
    )

    persisted = ChangeAnalysisWorkflowResult.model_validate(store.task.result)
    assert result["remaining"] == 0
    assert result["artifact_id"] == "streaming-response"
    assert persisted.checkpoint.findings[0].id == "streaming-response"
    assert persisted.checkpoint.findings[0].kind is ReleaseChangeKind.INTERNAL
    assert (
        persisted.checkpoint.findings[0].confidence
        is ReleaseChangeConfidence.HIGH
    )
    assert persisted.checkpoint.coverage[0].finding_id == "streaming-response"


def test_no_significant_changes_is_saved_as_an_artifact(monkeypatch) -> None:
    task = ProjectWorkflowTask(
        id="analysis-1",
        project_id="project-1",
        kind=ProjectWorkflowTaskKind.CHANGE_ANALYSIS,
        status=ProjectWorkflowTaskStatus.RUNNING,
        input=ChangeAnalysisWorkflowInput(run_id="run-1", plan_task_id="plan-1"),
    )

    class WorkflowStore:
        def get(self, _task_id):
            return task

        def save(self, saved):
            nonlocal task
            task = saved
            return saved

    class FakeAgent:
        def __init__(self) -> None:
            self.tools = {}

        def tool(self, function=None, **_kwargs):
            def register(candidate):
                self.tools[candidate.__name__] = candidate
                return candidate

            return register(function) if function is not None else register

    monkeypatch.setattr(
        change_analysis_orchestrator,
        "create_project_workflow_store",
        WorkflowStore,
    )
    agent = FakeAgent()
    register_change_analysis_orchestrator_tools(agent)
    deps = ChangeAnalysisOrchestratorDeps(
        project_id="project-1",
        run_id="run-1",
        workflow_task_id=task.id,
        inventory=ChangeAnalysisInventory(run_id="run-1", items=[]),
        checkpoint=ChangeAnalysisCheckpoint(),
        audience="developers",
    )

    result = agent.tools["save_change_artifact"](
        SimpleNamespace(deps=deps),
        artifact_id="no-significant-changes",
        title="No significant release-note changes",
        kind="internal",
        technical_summary="The selected range contains no material product changes.",
        user_impact="No user-visible release-note entry is needed.",
        coverage_keys=[],
        evidence_refs=[],
        release_note_eligible=False,
        confidence="high",
    )

    persisted = ChangeAnalysisWorkflowResult.model_validate(task.result)
    assert result["artifact_id"] == "no-significant-changes"
    assert persisted.checkpoint.findings[0].release_note_eligible is False
    assert persisted.checkpoint.findings[0].coverage_keys == []


def test_save_artifact_rejects_unknown_kind_as_correctable_tool_error(monkeypatch) -> None:
    inventory, _ = semantic_analysis_fixture()
    task = ProjectWorkflowTask(
        id="analysis-1",
        project_id="project-1",
        kind=ProjectWorkflowTaskKind.CHANGE_ANALYSIS,
        status=ProjectWorkflowTaskStatus.RUNNING,
        input=ChangeAnalysisWorkflowInput(run_id="run-1", plan_task_id="plan-1"),
    )

    class FakeAgent:
        def __init__(self) -> None:
            self.tools = {}

        def tool(self, function=None, **_kwargs):
            def register(candidate):
                self.tools[candidate.__name__] = candidate
                return candidate

            return register(function) if function is not None else register

    monkeypatch.setattr(
        change_analysis_orchestrator,
        "create_project_workflow_store",
        lambda: SimpleNamespace(get=lambda _task_id: task),
    )
    agent = FakeAgent()
    register_change_analysis_orchestrator_tools(agent)
    deps = ChangeAnalysisOrchestratorDeps(
        project_id="project-1",
        run_id="run-1",
        workflow_task_id=task.id,
        inventory=inventory,
        checkpoint=ChangeAnalysisCheckpoint(),
        audience="developers",
    )

    with pytest.raises(ModelRetry, match="kind must be one of"):
        agent.tools["save_change_artifact"](
            SimpleNamespace(deps=deps),
            artifact_id="invalid-kind",
            title="Invalid kind",
            kind="unexpected",
            technical_summary="A model supplied an unsupported value.",
            user_impact="No persisted impact.",
            coverage_keys=[inventory.items[0].key],
            evidence_refs=[],
        )


def test_orchestrator_prompt_keeps_inventory_and_findings_behind_tools() -> None:
    related_paths = [f"docs/translated-{index}.md" for index in range(200)]
    item = ChangeAnalysisInventoryItem(
        key="commit:repo-1:abc123",
        kind=ChangeAnalysisInventoryItemKind.COMMIT,
        repository_id="repo-1",
        summary="Update translated documentation",
        commit_sha="abc123",
        related_paths=related_paths,
        base_ref="abc123^",
        head_ref="abc123",
    )
    finding = ReleaseChangeFinding(
        id="docs-update",
        title="Documentation update",
        kind=ReleaseChangeKind.DOCUMENTATION,
        technical_summary="Reference documentation changed.",
        user_impact="Readers see updated guidance.",
        coverage_keys=[],
        evidence_refs=[],
    )
    deps = ChangeAnalysisOrchestratorDeps(
        project_id="project-1",
        run_id="run-1",
        workflow_task_id="analysis-1",
        inventory=ChangeAnalysisInventory(run_id="run-1", items=[item]),
        checkpoint=ChangeAnalysisCheckpoint(findings=[finding]),
        audience="developers",
    )

    prompt = orchestrator_runtime.orchestrator_user_prompt(deps, 1)

    assert "list_change_inventory" in prompt
    assert item.key not in prompt
    assert related_paths[0] not in prompt
    assert finding.technical_summary not in prompt
    assert len(prompt) < 3_000


def test_inventory_tools_page_compact_summaries_and_item_details() -> None:
    related_paths = [f"docs/translated-{index}.md" for index in range(80)]
    item = ChangeAnalysisInventoryItem(
        key="commit:repo-1:abc123",
        kind=ChangeAnalysisInventoryItemKind.COMMIT,
        repository_id="repo-1",
        summary="Update translated documentation",
        commit_sha="abc123",
        related_paths=related_paths,
        base_ref="abc123^",
        head_ref="abc123",
    )

    class FakeAgent:
        def __init__(self) -> None:
            self.tools = {}

        def tool(self, function=None, **_kwargs):
            def register(candidate):
                self.tools[candidate.__name__] = candidate
                return candidate

            return register(function) if function is not None else register

    agent = FakeAgent()
    register_change_analysis_orchestrator_tools(agent)
    assert "mark_no_release_note" not in agent.tools
    assert "save_release_finding" not in agent.tools
    assert "save_change_artifact" in agent.tools
    deps = ChangeAnalysisOrchestratorDeps(
        project_id="project-1",
        run_id="run-1",
        workflow_task_id="analysis-1",
        inventory=ChangeAnalysisInventory(run_id="run-1", items=[item]),
        checkpoint=ChangeAnalysisCheckpoint(),
        audience="developers",
    )
    context = SimpleNamespace(deps=deps)

    page = agent.tools["list_change_inventory"](context)
    detail = agent.tools["read_change_inventory_item"](
        context,
        item.key,
        related_paths_limit=50,
    )

    assert page["items"][0]["related_path_count"] == 80
    assert "related_paths" not in page["items"][0]
    assert len(detail["related_paths"]) == 50
    assert detail["related_paths_has_more"] is True
    assert detail["related_paths_next_offset"] == 50


def test_orchestrator_requires_at_least_one_persisted_artifact(monkeypatch) -> None:
    inventory, _ = semantic_analysis_fixture()
    deps = ChangeAnalysisOrchestratorDeps(
        project_id="project-1",
        run_id="run-1",
        workflow_task_id="analysis-1",
        inventory=inventory,
        checkpoint=ChangeAnalysisCheckpoint(),
        audience="developers",
    )

    monkeypatch.setattr(orchestrator_runtime, "deterministic_analysis_enabled", lambda: False)
    monkeypatch.setattr(
        orchestrator_runtime,
        "run_orchestrator_pass",
        lambda *_: ("Analysis complete.", "transcript-1"),
    )
    monkeypatch.setattr(orchestrator_runtime, "persist_checkpoint", lambda _: None)

    with pytest.raises(RuntimeError, match="without saving an analysis artifact"):
        orchestrator_runtime.run_change_analysis_orchestrator(deps)


def test_orchestrator_continues_in_bounded_passes_until_coverage_is_complete(
    monkeypatch,
) -> None:
    items = [
        ChangeAnalysisInventoryItem(
            key=f"commit:repo-1:sha-{index}",
            kind=ChangeAnalysisInventoryItemKind.COMMIT,
            repository_id="repo-1",
            summary=f"Change {index}",
            commit_sha=f"sha-{index}",
            base_ref=f"sha-{index}^",
            head_ref=f"sha-{index}",
        )
        for index in range(3)
    ]
    deps = ChangeAnalysisOrchestratorDeps(
        project_id="project-1",
        run_id="run-1",
        workflow_task_id="analysis-1",
        inventory=ChangeAnalysisInventory(run_id="run-1", items=items),
        checkpoint=ChangeAnalysisCheckpoint(),
        audience="developers",
    )
    observed_passes = []

    def fake_pass(current_deps, pass_number):
        observed_passes.append(pass_number)
        item = orchestrator_runtime.uncovered_inventory(
            current_deps.inventory,
            current_deps.checkpoint,
        )[0]
        orchestrator_runtime.replace_finding(
            current_deps.checkpoint,
            ReleaseChangeFinding(
                id=f"artifact-{pass_number}",
                title=f"Artifact {pass_number}",
                kind=ReleaseChangeKind.INTERNAL,
                technical_summary="One bounded inventory page was analyzed.",
                user_impact="No separate user-facing impact.",
                coverage_keys=[item.key],
                evidence_refs=[f"inventory:{item.key}"],
                release_note_eligible=False,
            ),
        )
        return "Saved one page.", f"tx-{pass_number}"

    monkeypatch.setattr(orchestrator_runtime, "deterministic_analysis_enabled", lambda: False)
    monkeypatch.setattr(orchestrator_runtime, "run_orchestrator_pass", fake_pass)
    monkeypatch.setattr(orchestrator_runtime, "persist_checkpoint", lambda _: None)

    result = orchestrator_runtime.run_change_analysis_orchestrator(deps)

    assert observed_passes == [1, 2, 3]
    assert result.checkpoint.completed is True
    assert result.checkpoint.transcript_ids == ["tx-1", "tx-2", "tx-3"]


def test_orchestrator_stops_at_bounded_pass_limit(monkeypatch) -> None:
    items = [
        ChangeAnalysisInventoryItem(
            key=f"commit:repo-1:sha-{index}",
            kind=ChangeAnalysisInventoryItemKind.COMMIT,
            repository_id="repo-1",
            summary=f"Change {index}",
            commit_sha=f"sha-{index}",
        )
        for index in range(2)
    ]
    deps = ChangeAnalysisOrchestratorDeps(
        project_id="project-1",
        run_id="run-1",
        workflow_task_id="analysis-1",
        inventory=ChangeAnalysisInventory(run_id="run-1", items=items),
        checkpoint=ChangeAnalysisCheckpoint(),
        audience="developers",
    )

    def fake_pass(current_deps, _pass_number):
        item = current_deps.inventory.items[0]
        orchestrator_runtime.replace_finding(
            current_deps.checkpoint,
            ReleaseChangeFinding(
                id="first-page",
                title="First page",
                kind=ReleaseChangeKind.INTERNAL,
                technical_summary="Only one page was processed.",
                user_impact="No separate user-facing impact.",
                coverage_keys=[item.key],
                evidence_refs=[f"inventory:{item.key}"],
                release_note_eligible=False,
            ),
        )
        return "Saved one page.", "tx-1"

    monkeypatch.setattr(orchestrator_runtime, "ORCHESTRATOR_PASS_LIMIT", 1)
    monkeypatch.setattr(orchestrator_runtime, "deterministic_analysis_enabled", lambda: False)
    monkeypatch.setattr(orchestrator_runtime, "run_orchestrator_pass", fake_pass)
    monkeypatch.setattr(orchestrator_runtime, "persist_checkpoint", lambda _: None)

    with pytest.raises(RuntimeError, match="bounded pass limit"):
        orchestrator_runtime.run_change_analysis_orchestrator(deps)


def test_coverage_without_an_artifact_does_not_complete_inventory() -> None:
    inventory, _ = semantic_analysis_fixture()
    checkpoint = ChangeAnalysisCheckpoint(
        coverage=[
            ChangeAnalysisCoverage(
                key=inventory.items[0].key,
                disposition=ChangeAnalysisCoverageDisposition.NO_RELEASE_NOTE,
                reason="Legacy coverage-only decision.",
            )
        ]
    )

    assert orchestrator_runtime.uncovered_inventory(inventory, checkpoint) == inventory.items


def test_orchestrator_rejects_incomplete_artifact_coverage(monkeypatch) -> None:
    inventory, checkpoint = semantic_analysis_fixture()
    second_item = ChangeAnalysisInventoryItem(
        key="path:repo-1:tests/test_app.py",
        kind=ChangeAnalysisInventoryItemKind.PATH,
        repository_id="repo-1",
        summary="M tests/test_app.py",
        path="tests/test_app.py",
        status="M",
        base_ref="base",
        head_ref="head",
    )
    deps = ChangeAnalysisOrchestratorDeps(
        project_id="project-1",
        run_id="run-1",
        workflow_task_id="analysis-1",
        inventory=inventory.model_copy(update={"items": [*inventory.items, second_item]}),
        checkpoint=checkpoint,
        audience="developers",
    )

    monkeypatch.setattr(orchestrator_runtime, "deterministic_analysis_enabled", lambda: False)
    monkeypatch.setattr(
        orchestrator_runtime,
        "run_orchestrator_pass",
        lambda *_: ("Saved the available artifact.", "transcript-1"),
    )
    monkeypatch.setattr(orchestrator_runtime, "persist_checkpoint", lambda _: None)

    with pytest.raises(RuntimeError, match=r"1 inventory item\(s\) remain"):
        orchestrator_runtime.run_change_analysis_orchestrator(deps)


def test_orchestrator_resume_processes_only_uncovered_inventory(monkeypatch) -> None:
    first_inventory, first_checkpoint = semantic_analysis_fixture()
    second_item = ChangeAnalysisInventoryItem(
        key="path:repo-1:tests/test_app.py",
        kind=ChangeAnalysisInventoryItemKind.PATH,
        repository_id="repo-1",
        summary="M tests/test_app.py",
        path="tests/test_app.py",
        status="M",
        base_ref="base",
        head_ref="head",
    )
    inventory = first_inventory.model_copy(
        update={"items": [*first_inventory.items, second_item]}
    )
    first_checkpoint.completed = False
    observed_batches = []

    def fake_pass(deps, _pass_number):
        observed_batches.append(
            [
                item.key
                for item in orchestrator_runtime.uncovered_inventory(
                    deps.inventory,
                    deps.checkpoint,
                )
            ]
        )
        finding = ReleaseChangeFinding(
            id="streaming-test",
            title="Verify streamed responses",
            kind=ReleaseChangeKind.INTERNAL,
            technical_summary="Tests cover streamed response behavior.",
            user_impact="No separate user-facing change.",
            coverage_keys=[second_item.key],
            evidence_refs=[f"inventory:{second_item.key}"],
            release_note_eligible=False,
        )
        orchestrator_runtime.replace_finding(deps.checkpoint, finding)
        return "Covered tests.", "tx-2"

    monkeypatch.setattr(orchestrator_runtime, "deterministic_analysis_enabled", lambda: False)
    monkeypatch.setattr(orchestrator_runtime, "run_orchestrator_pass", fake_pass)
    monkeypatch.setattr(orchestrator_runtime, "persist_checkpoint", lambda _: None)
    deps = ChangeAnalysisOrchestratorDeps(
        project_id="project-1",
        run_id="run-1",
        workflow_task_id="analysis-1",
        inventory=inventory,
        checkpoint=first_checkpoint,
        audience="developers",
    )

    result = orchestrator_runtime.run_change_analysis_orchestrator(deps)

    assert observed_batches == [[second_item.key]]
    assert result.checkpoint.completed is True
    assert [finding.id for finding in result.checkpoint.findings] == [
        "streaming-response",
        "streaming-test",
    ]


def test_finding_update_absorbs_new_coverage_without_reassigning_old_keys() -> None:
    inventory, checkpoint = semantic_analysis_fixture()
    second_key = "path:repo-1:tests/test_app.py"
    updated = checkpoint.findings[0].model_copy(
        update={
            "coverage_keys": [second_key],
            "evidence_refs": [f"inventory:{second_key}"],
        }
    )

    orchestrator_runtime.replace_finding(checkpoint, updated)

    assert checkpoint.findings[0].coverage_keys == [
        inventory.items[0].key,
        second_key,
    ]
    assert {item.key for item in checkpoint.coverage} == {
        inventory.items[0].key,
        second_key,
    }


def test_finding_cannot_steal_durable_coverage() -> None:
    inventory, checkpoint = semantic_analysis_fixture()
    deps = ChangeAnalysisOrchestratorDeps(
        project_id="project-1",
        run_id="run-1",
        workflow_task_id="analysis-1",
        inventory=inventory,
        checkpoint=checkpoint,
        audience="developers",
    )

    with pytest.raises(ValueError, match="already have durable coverage"):
        change_analysis_orchestrator.validated_inventory_keys(
            deps,
            [inventory.items[0].key],
            finding_id="different-finding",
        )


def test_failed_synthesis_stops_before_knowledge_refresh(monkeypatch, tmp_path) -> None:
    request = GuideSyncRunRequest(run_id="run-1", goal="Draft documentation.")
    request.report.output_dir = tmp_path
    run = GuideSyncRunResult(
        run_id=request.run_id,
        status="running",
        request=request,
        evidence=EvidenceBundle(),
    )
    inventory, checkpoint = semantic_analysis_fixture()
    analysis_task = ProjectWorkflowTask(
        id="analysis-1",
        project_id="project-1",
        kind=ProjectWorkflowTaskKind.CHANGE_ANALYSIS,
        status=ProjectWorkflowTaskStatus.COMPLETED,
        input=ChangeAnalysisWorkflowInput(run_id=run.run_id, plan_task_id="plan-1"),
        result=ChangeAnalysisWorkflowResult(inventory=inventory, checkpoint=checkpoint),
    )
    task = ProjectWorkflowTask(
        project_id="project-1",
        kind=ProjectWorkflowTaskKind.CHANGE_SYNTHESIS,
        input=ChangeSynthesisWorkflowInput(
            run_id=run.run_id,
            plan_task_id="plan-1",
            analysis_task_id=analysis_task.id,
        ),
    )

    monkeypatch.setattr(workflow_change_analysis, "require_workflow_run", lambda _: run)
    monkeypatch.setattr(
        workflow_change_analysis,
        "require_completed_workflow_task",
        lambda _: analysis_task,
    )
    monkeypatch.setattr(
        workflow_change_analysis,
        "prepare_documentation_update_from_summaries",
        lambda *args, **kwargs: SimpleNamespace(),
    )

    async def failed_run(*args, **kwargs):
        return run.model_copy(update={"status": "failed"})

    monkeypatch.setattr(workflow_change_analysis, "run_guidesync", failed_run)

    with pytest.raises(RuntimeError, match="knowledge refresh was skipped"):
        asyncio.run(workflow_change_analysis.execute_change_synthesis(task))
