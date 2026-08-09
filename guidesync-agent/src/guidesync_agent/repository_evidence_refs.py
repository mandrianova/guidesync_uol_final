from __future__ import annotations

REPOSITORY_EVIDENCE_ROOT = "/repositories"


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


def normalize_repository_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/").removeprefix("./")
    if normalized.startswith(f"{REPOSITORY_EVIDENCE_ROOT}/"):
        virtual_path = normalized.removeprefix(
            f"{REPOSITORY_EVIDENCE_ROOT}/"
        )
        _, separator, relative_path = virtual_path.partition("/")
        normalized = relative_path if separator else "."
    normalized = normalized.strip("/")
    return normalized or "."
