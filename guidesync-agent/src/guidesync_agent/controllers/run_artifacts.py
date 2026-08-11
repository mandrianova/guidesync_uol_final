from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from guidesync_agent.reports import read_artifact
from guidesync_agent.schemas import PublicationReport
from guidesync_agent.storage import create_run_store


class RunArtifactError(Exception):
    """Base class for run artifact lookup failures."""


class RunNotFoundError(RunArtifactError):
    """Raised when a run id cannot be found."""


class InvalidArtifactFilenameError(RunArtifactError):
    """Raised when a filename is not safe to resolve as a run artifact."""


class ArtifactNotFoundError(RunArtifactError):
    """Raised when the run exists but does not reference the requested artifact."""


class ArtifactFileNotFoundError(RunArtifactError):
    """Raised when the stored artifact reference points to a missing file."""


class ArtifactReadError(RunArtifactError):
    """Raised when the stored artifact reference cannot be read."""


@dataclass(frozen=True)
class ArtifactPayload:
    body: bytes
    media_type: str
    headers: dict[str, str]


@dataclass(frozen=True)
class ArtifactRedirect:
    url: str


def get_run_artifact(
    run_id: str,
    filename: str,
) -> ArtifactPayload | ArtifactRedirect:
    validate_artifact_filename(filename)
    uri = artifact_uri(run_id, filename)
    return load_stored_artifact(filename, uri)


def get_publication_report(run_id: str) -> PublicationReport:
    store = create_run_store()
    if not store.run_exists(run_id):
        raise RunNotFoundError(f"Run not found: {run_id}")
    try:
        report = store.get_publication_report(run_id)
    except ValidationError as exc:
        raise ArtifactReadError(f"Invalid persisted publication report: {exc}") from exc
    if report is None:
        raise ArtifactNotFoundError(f"Publication report not available for run: {run_id}")
    return report


def validate_artifact_filename(filename: str) -> None:
    if "/" in filename or "\\" in filename:
        raise InvalidArtifactFilenameError("Invalid artifact filename.")


def load_stored_artifact(
    filename: str,
    uri: str,
) -> ArtifactPayload | ArtifactRedirect:
    if uri.startswith(("http://", "https://")):
        return ArtifactRedirect(uri)

    try:
        artifact = read_artifact(uri)
    except FileNotFoundError as exc:
        raise ArtifactFileNotFoundError(f"Artifact file not found: {filename}") from exc
    except ValueError as exc:
        raise ArtifactReadError(str(exc)) from exc

    inline_media = artifact.content_type.startswith(("image/", "audio/", "video/"))
    disposition = "inline" if inline_media else "attachment"
    return ArtifactPayload(
        body=artifact.body,
        media_type=artifact.content_type,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


def artifact_uri(run_id: str, filename: str) -> str:
    store = create_run_store()
    uri = store.get_artifact_uri(run_id, filename)
    if uri:
        return uri
    if not store.run_exists(run_id):
        raise RunNotFoundError(f"Run not found: {run_id}")
    raise ArtifactNotFoundError(f"Artifact not found: {filename}")
