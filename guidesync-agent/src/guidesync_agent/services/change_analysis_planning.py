from __future__ import annotations

import re
from collections import defaultdict
from hashlib import sha256
from pathlib import PurePosixPath

from guidesync_agent.schemas import ChangeAnalysisWorkUnit, ChangedFileRef

MAX_FILES_PER_ANALYSIS_UNIT = 4
TEST_PATH_PARTS = {"test", "tests", "__tests__", "spec", "specs"}
CONFIG_NAMES = {
    "cargo.lock",
    "composer.lock",
    "package-lock.json",
    "package.json",
    "poetry.lock",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "yarn.lock",
}
GENERIC_TEST_TOKENS = {
    "init",
    "spec",
    "specs",
    "test",
    "tests",
    "tutorial",
}


def build_change_analysis_work_units(
    repository_id: str,
    changed_files: list[ChangedFileRef],
    *,
    base_ref: str | None,
    head_ref: str,
) -> list[ChangeAnalysisWorkUnit]:
    ordered = sorted(changed_files, key=lambda item: item.path)
    remaining_tests = [item for item in ordered if is_test_path(item.path)]
    implementation_files = sorted(
        (item for item in ordered if not is_test_path(item.path)),
        key=lambda item: (is_documentation_path(item.path), item.path),
    )
    units: list[ChangeAnalysisWorkUnit] = []
    grouped_files: dict[str, list[ChangedFileRef]] = defaultdict(list)

    for changed_file in implementation_files:
        related_tests = [
            item
            for item in remaining_tests
            if related_file_key(item.path) == related_file_key(changed_file.path)
        ][: MAX_FILES_PER_ANALYSIS_UNIT - 1]
        remaining_tests = [item for item in remaining_tests if item not in related_tests]
        if related_tests:
            units.append(
                work_unit(
                    repository_id,
                    [changed_file, *related_tests],
                    base_ref=base_ref,
                    head_ref=head_ref,
                    grouping_reason="implementation with related tests",
                )
            )
            continue
        grouped_files[change_family(changed_file.path)].append(changed_file)

    for test_file in remaining_tests:
        grouped_files[f"tests:{test_feature(test_file.path)}"].append(test_file)

    for family, files in grouped_files.items():
        units.extend(
            work_unit(
                repository_id,
                files[index : index + MAX_FILES_PER_ANALYSIS_UNIT],
                base_ref=base_ref,
                head_ref=head_ref,
                grouping_reason=f"cohesive {family.replace(':', ' ')} change set",
            )
            for index in range(0, len(files), MAX_FILES_PER_ANALYSIS_UNIT)
        )
    validate_work_unit_coverage(ordered, units)
    return units


def work_unit(
    repository_id: str,
    files: list[ChangedFileRef],
    *,
    base_ref: str | None,
    head_ref: str,
    grouping_reason: str,
) -> ChangeAnalysisWorkUnit:
    paths = [item.path for item in files]
    digest = sha256(f"{repository_id}:{'|'.join(paths)}".encode()).hexdigest()[:12]
    return ChangeAnalysisWorkUnit(
        id=f"analysis-unit-{digest}",
        repository_id=repository_id,
        files=files,
        base_ref=base_ref,
        head_ref=head_ref,
        grouping_reason=grouping_reason,
    )


def is_test_path(path: str) -> bool:
    path_obj = PurePosixPath(path)
    parts = {part.lower() for part in path_obj.parts}
    name = path_obj.name.lower()
    return (
        bool(parts & TEST_PATH_PARTS)
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def related_file_key(path: str) -> str:
    stem = PurePosixPath(path).stem.lower()
    for prefix in ("test_", "spec_"):
        stem = stem.removeprefix(prefix)
    for suffix in ("_test", "_spec", ".test", ".spec"):
        stem = stem.removesuffix(suffix)
    return stem


def is_documentation_path(path: str) -> bool:
    path_obj = PurePosixPath(path)
    parts = {part.lower() for part in path_obj.parts}
    return path_obj.suffix.lower() in {".md", ".mdx", ".rst"} or bool(
        parts & {"doc", "docs", "documentation"}
    )


def change_family(path: str) -> str:
    path_obj = PurePosixPath(path)
    if path_obj.name.lower() in CONFIG_NAMES:
        return "configuration"
    if is_documentation_path(path):
        return f"documentation:{top_level_scope(path_obj)}"
    return f"source:{top_level_scope(path_obj)}"


def top_level_scope(path: PurePosixPath) -> str:
    return path.parts[0].lower() if len(path.parts) > 1 else "root"


def test_feature(path: str) -> str:
    tokens = re.findall(r"[a-z][a-z0-9]*", path.lower())
    return next(
        (
            token
            for token in tokens
            if token not in GENERIC_TEST_TOKENS
            and not token.startswith("tutorial")
            and token not in {"py", "js", "ts", "tsx"}
        ),
        "unmatched",
    )


def validate_work_unit_coverage(
    changed_files: list[ChangedFileRef],
    units: list[ChangeAnalysisWorkUnit],
) -> None:
    planned = [item.path for unit in units for item in unit.files]
    expected = [item.path for item in changed_files]
    if sorted(planned) != sorted(expected) or len(planned) != len(set(planned)):
        raise ValueError("Change-analysis work units must cover every changed file exactly once.")
