from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

REPOSITORY_EVIDENCE_ROOT = "/repositories"


@dataclass(frozen=True)
class ParsedRepositoryEvidenceRef:
    repository_id: str
    path: str
    line_number: int | None = None


def repository_evidence_ref(
    repository_id: str,
    path: str,
    *,
    is_directory: bool = False,
    line_number: int | None = None,
) -> str:
    relative_path = normalize_repository_path(path)
    if relative_path == ".":
        source = f"{REPOSITORY_EVIDENCE_ROOT}/{repository_id}/"
    else:
        source = f"{REPOSITORY_EVIDENCE_ROOT}/{repository_id}/{relative_path}"
        if is_directory and not source.endswith("/"):
            source += "/"
    if line_number is not None:
        return f"{source}#L{line_number}"
    return source


def canonical_repository_evidence_ref(value: str, repository_id: str | None = None) -> str | None:
    parsed = parse_repository_evidence_ref(value)
    if parsed is not None:
        return repository_evidence_ref(
            parsed.repository_id,
            parsed.path,
            line_number=parsed.line_number,
        )
    if repository_id:
        return repository_evidence_ref(repository_id, value)
    return None


def parse_repository_evidence_ref(value: str) -> ParsedRepositoryEvidenceRef | None:
    cleaned = value.strip().replace("\\", "/")
    if cleaned.startswith(f"{REPOSITORY_EVIDENCE_ROOT}/"):
        return parse_slash_repository_ref(cleaned)
    if cleaned.startswith("repo:"):
        return parse_legacy_repository_ref(cleaned)
    return None


def parse_slash_repository_ref(value: str) -> ParsedRepositoryEvidenceRef | None:
    source, line_number = split_line_suffix(value)
    parts = PurePosixPath(source).parts
    if len(parts) < 3 or parts[1] != REPOSITORY_EVIDENCE_ROOT.removeprefix("/"):
        return None
    repository_id = parts[2]
    path = PurePosixPath(*parts[3:]).as_posix() if len(parts) > 3 else "."
    return ParsedRepositoryEvidenceRef(repository_id, normalize_repository_path(path), line_number)


def parse_legacy_repository_ref(value: str) -> ParsedRepositoryEvidenceRef | None:
    parts = value.split(":", 2)
    if len(parts) != 3:
        return None
    _, repository_id, path = parts
    path, line_number = split_legacy_line_suffix(path)
    return ParsedRepositoryEvidenceRef(repository_id, normalize_repository_path(path), line_number)


def split_line_suffix(value: str) -> tuple[str, int | None]:
    source, marker, suffix = value.rpartition("#L")
    if marker and suffix.isdigit():
        return source, int(suffix)
    return value, None


def split_legacy_line_suffix(path: str) -> tuple[str, int | None]:
    source, marker, suffix = path.rpartition(":line:")
    if marker and suffix.isdigit():
        return source, int(suffix)
    source, marker, suffix = path.rpartition(":L")
    if marker and suffix.isdigit():
        return source, int(suffix)
    return path, None


def normalize_repository_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/").removeprefix("./")
    parsed = parse_slash_repository_ref(normalized) if normalized.startswith("/") else None
    if parsed is not None:
        return parsed.path
    normalized = normalized.strip("/")
    return normalized or "."
