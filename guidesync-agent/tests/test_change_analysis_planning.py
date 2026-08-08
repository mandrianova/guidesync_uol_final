from __future__ import annotations

from guidesync_agent.schemas import ChangedFileRef
from guidesync_agent.services.change_analysis_planning import (
    build_change_analysis_work_units,
)


def test_work_plan_covers_every_file_and_groups_related_tests() -> None:
    changed_files = [
        ChangedFileRef(path="src/widget.py", status="M"),
        ChangedFileRef(path="tests/test_widget.py", status="M"),
        ChangedFileRef(path="docs/widget.md", status="M"),
        ChangedFileRef(path="src/other.py", status="A"),
    ]

    units = build_change_analysis_work_units(
        "repo-plan",
        changed_files,
        base_ref="main",
        head_ref="HEAD",
    )

    planned_paths = [item.path for unit in units for item in unit.files]
    widget_unit = next(unit for unit in units if unit.files[0].path == "src/widget.py")
    assert sorted(planned_paths) == sorted(item.path for item in changed_files)
    assert len(planned_paths) == len(set(planned_paths))
    assert [item.path for item in widget_unit.files] == [
        "src/widget.py",
        "tests/test_widget.py",
    ]
    assert widget_unit.grouping_reason == "implementation with related tests"
    assert widget_unit.connectivity_evidence == ["shared normalized file key: widget"]


def test_fastapi_streaming_change_is_not_split_into_thirteen_file_tasks() -> None:
    changed_files = [
        ChangedFileRef(path="fastapi/dependencies/utils.py", status="M"),
        ChangedFileRef(path="fastapi/openapi/utils.py", status="M"),
        ChangedFileRef(path="fastapi/routing.py", status="M"),
        ChangedFileRef(path="pyproject.toml", status="M"),
        ChangedFileRef(path="uv.lock", status="M"),
        ChangedFileRef(path="tests/test_stream_bare_type.py", status="A"),
        ChangedFileRef(path="tests/test_stream_cancellation.py", status="A"),
        ChangedFileRef(path="tests/test_stream_json_validation_error.py", status="A"),
        ChangedFileRef(path="tests/test_tutorial/test_stream_data/__init__.py", status="A"),
        ChangedFileRef(
            path="tests/test_tutorial/test_stream_data/test_tutorial001.py",
            status="A",
        ),
        ChangedFileRef(
            path="tests/test_tutorial/test_stream_data/test_tutorial002.py",
            status="A",
        ),
        ChangedFileRef(path="tests/test_tutorial/test_stream_json_lines/__init__.py", status="A"),
        ChangedFileRef(
            path="tests/test_tutorial/test_stream_json_lines/test_tutorial001.py",
            status="A",
        ),
    ]

    units = build_change_analysis_work_units(
        "fastapi-pr-15022",
        changed_files,
        base_ref="HEAD~1",
        head_ref="HEAD",
    )

    planned_paths = [item.path for unit in units for item in unit.files]
    assert len(units) == 4
    assert sorted(planned_paths) == sorted(item.path for item in changed_files)
    assert len(planned_paths) == len(set(planned_paths))
    assert [len(unit.files) for unit in units] == [3, 2, 4, 4]
    assert all(unit.connectivity_evidence for unit in units)
