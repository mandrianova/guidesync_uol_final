from datetime import UTC, datetime

from guidesync_agent.schemas import (
    EvidenceBundle,
    GuideSyncRunRequest,
    GuideSyncRunResult,
    ReportChangeScope,
    RepositoryInput,
)
from guidesync_agent.storage.serialization_runs import run_summary


def test_report_change_scope_keeps_selected_period() -> None:
    scope = ReportChangeScope.from_repositories(
        [
            RepositoryInput(
                name="web-app",
                repository_id="repo-web",
                since="2026-08-01",
                until="2026-08-09",
                branches=["main"],
            )
        ]
    )

    assert scope.repositories[0].model_dump() == {
        "name": "web-app",
        "since": "2026-08-01",
        "until": "2026-08-09",
        "branches": ["main"],
    }


def test_report_change_scope_groups_selected_branches() -> None:
    scope = ReportChangeScope.from_repositories(
        [
            RepositoryInput(
                name="solutions-ui [main]",
                repository_id="repo-ui",
                since=None,
                branches=["main"],
            ),
            RepositoryInput(
                name="solutions-ui [billing-overhaul]",
                repository_id="repo-ui",
                since=None,
                branches=["billing-overhaul"],
            ),
        ]
    )

    assert len(scope.repositories) == 1
    assert scope.repositories[0].name == "solutions-ui"
    assert scope.repositories[0].branches == ["main", "billing-overhaul"]


def test_run_summary_exposes_change_scope() -> None:
    request = GuideSyncRunRequest(
        run_id="project-demo-run",
        goal="Summarize selected changes.",
        repositories=[
            RepositoryInput(
                name="web-app",
                repository_id="repo-web",
                since="2026-08-01",
                until="2026-08-09",
            )
        ],
    )
    result = GuideSyncRunResult(
        run_id=request.run_id,
        status="completed",
        request=request,
        evidence=EvidenceBundle(),
    )
    now = datetime(2026, 8, 10, tzinfo=UTC)

    summary = run_summary(
        result,
        created_at=now,
        updated_at=now,
        publication_available=False,
    )

    assert summary.change_scope.repositories[0].since == "2026-08-01"
    assert summary.change_scope.repositories[0].until == "2026-08-09"
