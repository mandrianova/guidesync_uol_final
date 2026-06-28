from __future__ import annotations

from dataclasses import dataclass

from guidesync_agent.reports import read_artifact, render_html
from guidesync_agent.reports_pdf import render_pdf
from guidesync_agent.schemas import GuideSyncRunResult
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
    *,
    print_view: bool = False,
) -> ArtifactPayload | ArtifactRedirect:
    result = create_run_store().get(run_id)
    if result is None:
        raise RunNotFoundError(f"Run not found: {run_id}")
    if "/" in filename or "\\" in filename:
        raise InvalidArtifactFilenameError("Invalid artifact filename.")
    if filename == "report.html":
        return _render_report_html(result, print_view=print_view)
    if filename == "report.pdf":
        return _render_report_pdf(result)

    uri = result.artifacts.get(filename)
    if not uri:
        raise ArtifactNotFoundError(f"Artifact not found: {filename}")
    if uri.startswith(("http://", "https://")):
        return ArtifactRedirect(uri)

    try:
        artifact = read_artifact(uri)
    except FileNotFoundError as exc:
        raise ArtifactFileNotFoundError(f"Artifact file not found: {filename}") from exc
    except ValueError as exc:
        raise ArtifactReadError(str(exc)) from exc

    body = artifact.body
    if print_view and filename.endswith(".html"):
        body = inject_print_script(body)
    return ArtifactPayload(
        body=body,
        media_type=artifact.content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _render_report_html(result: GuideSyncRunResult, *, print_view: bool) -> ArtifactPayload:
    body = render_html(result).encode("utf-8")
    if print_view:
        body = inject_print_script(body)
    return ArtifactPayload(
        body=body,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="report.html"'},
    )


def _render_report_pdf(result: GuideSyncRunResult) -> ArtifactPayload:
    return ArtifactPayload(
        body=render_pdf(result),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="report.pdf"'},
    )


def inject_print_script(body: bytes) -> bytes:
    html = body.decode("utf-8", errors="replace")
    script = "<script>window.addEventListener('load', () => window.print());</script>"
    if "</body>" in html:
        html = html.replace("</body>", f"{script}</body>")
    else:
        html += script
    return html.encode("utf-8")
