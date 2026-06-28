from __future__ import annotations

import re
from collections.abc import Iterable

from guidesync_agent.schemas import (
    AgentLoopActionType,
    AgentLoopModelAction,
    AgentLoopObservation,
    AgentLoopPromptContext,
    AgentLoopToolCall,
    AgentLoopToolName,
    ProjectProfileAgentEvidence,
    ProjectProfileAgentOutput,
    ProjectProfileAgentRequest,
    ProjectProfileDirectoryRef,
    ProjectProfileFileListing,
    ProjectProfileFileRef,
    ProjectProfileFileSelection,
    ProjectProfileSelectedFile,
    RepositoryFilesystemResult,
    RepositoryFileWindow,
    ToolPagination,
)


class FakeProjectProfileAgentProvider:
    provider = "fake"
    model = "fixture-agent"

    def next_action(self, context: AgentLoopPromptContext) -> AgentLoopModelAction:
        request = ProjectProfileAgentRequest.model_validate(context.request.context)
        repository_id = request.repositories[0].repository_id if request.repositories else ""
        root_path = f"/repositories/{repository_id}/"
        if not observations_for(context.observations, AgentLoopToolName.LIST_DIRECTORY):
            return AgentLoopModelAction(
                action=AgentLoopActionType.TOOL_CALL,
                tool_call=AgentLoopToolCall(
                    tool_name=AgentLoopToolName.LIST_DIRECTORY,
                    arguments={"path": root_path},
                    reason="fixture provider starts by listing the repository root",
                ),
            )

        selected_paths = selected_fixture_paths(context.observations)
        read_paths = {
            filesystem_relative_path(observation)
            for observation in observations_for(
                context.observations,
                AgentLoopToolName.READ_TEXT_FILE,
            )
        }
        next_path = next((path for path in selected_paths if path not in read_paths), None)
        if next_path is not None:
            return AgentLoopModelAction(
                action=AgentLoopActionType.TOOL_CALL,
                tool_call=AgentLoopToolCall(
                    tool_name=AgentLoopToolName.READ_TEXT_FILE,
                    arguments={
                        "path": f"/repositories/{repository_id}/{next_path}",
                    },
                    reason="fixture provider reads high-signal project evidence",
                ),
            )

        next_directory = next_fixture_directory_to_expand(context.observations)
        if next_directory is not None:
            return AgentLoopModelAction(
                action=AgentLoopActionType.TOOL_CALL,
                tool_call=AgentLoopToolCall(
                    tool_name=AgentLoopToolName.LIST_DIRECTORY,
                    arguments={"path": next_directory},
                    reason="fixture provider expands a high-signal repository directory",
                ),
            )

        evidence = fake_evidence_from_observations(context.observations)
        selection = ProjectProfileFileSelection(
            files_to_read=[
                ProjectProfileSelectedFile(
                    repository_id=window.repository_id,
                    path=window.path,
                    reason="read by fixture loop",
                )
                for window in evidence.file_windows
            ],
            reasoning_summary="fixture provider completed a free loop",
        )
        output = ProjectProfileAgentOutput.model_validate(
            self.build_profile(request, evidence, selection)
        )
        return AgentLoopModelAction(
            action=AgentLoopActionType.FINAL,
            final_output=output.model_dump(mode="json"),
            reasoning_summary="fixture provider has enough repository evidence",
        )

    def select_files(
        self,
        request: ProjectProfileAgentRequest,
        file_listings: list[ProjectProfileFileListing],
    ) -> object:
        candidates = [file for listing in file_listings for file in listing.files]
        scored = sorted(candidates, key=lambda item: (-fake_file_score(item.path), item.path))
        return ProjectProfileFileSelection(
            files_to_read=[
                ProjectProfileSelectedFile(
                    repository_id=file.repository_id,
                    path=file.path,
                    reason="fixture provider selected high-signal project file",
                )
                for file in scored[: min(8, request.budget.max_tool_calls)]
            ],
            search_queries=[],
            reasoning_summary="fixture provider selected docs, source, and config files",
        )

    def build_profile(
        self,
        request: ProjectProfileAgentRequest,
        evidence: ProjectProfileAgentEvidence,
        selection: ProjectProfileFileSelection,
    ) -> object:
        texts = {window.path: window.content for window in evidence.file_windows if window.ok}
        headings = extract_headings(texts.values())
        architecture = markdown_bullets(headings[:6] or ["Repository-backed documentation flow"])
        components = extract_components(texts.keys(), texts.values())
        categories = fake_categories(texts)
        domain_terms = fake_domain_terms(texts.values())
        project_structure = markdown_bullets(fake_project_structure(texts.keys()))
        core_concepts = unique_terms([*categories, *components, *domain_terms])[:16]
        project_description = (
            f"{request.name} is profiled from repository evidence"
            f" across {len(texts)} selected files."
        )
        return ProjectProfileAgentOutput(
            summary=f"{request.name} profile generated from repository evidence.",
            project_description=project_description,
            project_structure=project_structure,
            architecture=architecture,
            core_concepts=core_concepts,
            categories=categories,
        )


def observations_for(
    observations: list[AgentLoopObservation],
    tool_name: AgentLoopToolName,
) -> list[AgentLoopObservation]:
    return [observation for observation in observations if observation.tool_name == tool_name]


def selected_fixture_paths(observations: list[AgentLoopObservation]) -> list[str]:
    files = []
    for observation in observations_for(observations, AgentLoopToolName.LIST_DIRECTORY):
        result = RepositoryFilesystemResult.model_validate(observation.payload)
        files.extend(
            item
            for item in result.entries
            if item.get("type") == "file" and isinstance(item.get("relative_path"), str)
        )
    scored = sorted(
        files,
        key=lambda item: (-fake_file_score(str(item["relative_path"])), str(item["relative_path"])),
    )
    return [str(item["relative_path"]) for item in scored[:8]]


def next_fixture_directory_to_expand(
    observations: list[AgentLoopObservation],
) -> str | None:
    expanded = set()
    directories = []
    for observation in observations_for(observations, AgentLoopToolName.LIST_DIRECTORY):
        path = observation.arguments.get("path")
        if isinstance(path, str):
            expanded.add(path)
        result = RepositoryFilesystemResult.model_validate(observation.payload)
        directories.extend(
            item
            for item in result.entries
            if item.get("type") == "directory" and isinstance(item.get("path"), str)
        )
    scored = sorted(
        directories,
        key=lambda item: (-fake_file_score(str(item["relative_path"])), str(item["path"])),
    )
    return next((str(item["path"]) for item in scored if str(item["path"]) not in expanded), None)


def fake_evidence_from_observations(
    observations: list[AgentLoopObservation],
) -> ProjectProfileAgentEvidence:
    listings = [
        file_listing_from_filesystem_observation(observation)
        for observation in observations_for(observations, AgentLoopToolName.LIST_DIRECTORY)
    ]
    windows = [
        file_window_from_filesystem_observation(observation)
        for observation in observations_for(observations, AgentLoopToolName.READ_TEXT_FILE)
    ]
    return ProjectProfileAgentEvidence(file_listings=listings, file_windows=windows)


def file_listing_from_filesystem_observation(
    observation: AgentLoopObservation,
) -> ProjectProfileFileListing:
    result = RepositoryFilesystemResult.model_validate(observation.payload)
    repository_id = result.repository_id or ""
    directories = []
    files = []
    for entry in result.entries:
        relative = str(entry.get("relative_path") or "")
        if not relative:
            continue
        ref = str(entry.get("evidence_ref") or evidence_ref(repository_id, relative))
        if entry.get("type") == "directory":
            directories.append(
                ProjectProfileDirectoryRef(
                    repository_id=repository_id,
                    path=relative,
                    evidence_ref=ref,
                )
            )
        elif entry.get("type") == "file":
            files.append(
                ProjectProfileFileRef(
                    repository_id=repository_id,
                    path=relative,
                    size_bytes=int(entry.get("size_bytes") or 0),
                    suffix=(
                        "." + relative.rsplit(".", maxsplit=1)[-1] if "." in relative else ""
                    ),
                    evidence_ref=ref,
                )
            )
    return ProjectProfileFileListing(
        ok=result.ok,
        project_id=result.roots[0].project_id if result.roots else "",
        repository_id=repository_id,
        path=filesystem_relative_path(observation),
        directories=directories,
        files=files,
        pagination=ToolPagination(
            offset=0,
            limit=len(result.entries) or 1,
            total=len(result.entries),
            truncated=result.truncated,
        ),
        error=result.error,
    )


def file_window_from_filesystem_observation(
    observation: AgentLoopObservation,
) -> RepositoryFileWindow:
    result = RepositoryFilesystemResult.model_validate(observation.payload)
    content = result.content if result.ok else ""
    return RepositoryFileWindow(
        ok=result.ok,
        repository_id=result.repository_id or "",
        path=filesystem_relative_path(observation),
        content=content,
        pagination=ToolPagination(
            offset=0,
            limit=max(1, len(content)),
            total=len(content),
            truncated=result.truncated,
        ),
        artifact_ref=result.artifact_ref,
        error=result.error,
    )


def filesystem_relative_path(observation: AgentLoopObservation) -> str:
    metadata = observation.payload.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("relative_path"), str):
        return metadata["relative_path"]
    path = observation.payload.get("path")
    if isinstance(path, str) and path.startswith("/repositories/"):
        parts = path.removeprefix("/repositories/").split("/", maxsplit=1)
        if len(parts) == 2 and parts[1]:
            return parts[1]
    return "."


def evidence_ref(repository_id: str, path: str) -> str:
    return f"repo:{repository_id}:{path}"


def fake_file_score(path: str) -> int:
    lowered = path.lower()
    score = 0
    if lowered.endswith((".md", ".mdx", ".rst")):
        score += 8
    if any(part in lowered for part in ["readme", "docs/", "src/", "app", "page", "route"]):
        score += 5
    if lowered.endswith((".py", ".ts", ".tsx", ".json", ".toml", ".yaml", ".yml")):
        score += 3
    return score


def extract_headings(texts: Iterable[str]) -> list[str]:
    headings: list[str] = []
    for text in texts:
        headings.extend(re.findall(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", text, flags=re.MULTILINE))
    return unique_terms(headings)


def extract_components(paths: Iterable[str], texts: Iterable[str]) -> list[str]:
    values: list[str] = []
    for path in paths:
        stem = path.rsplit("/", maxsplit=1)[-1].split(".", maxsplit=1)[0]
        if re.search(r"[A-Z][a-z]+[A-Za-z]*", stem):
            values.append(stem)
    for text in texts:
        values.extend(
            re.findall(r"\b(?:class|function|def|const)\s+([A-Za-z_][A-Za-z0-9_]*)", text)
        )
    return unique_terms(values)[:12]


def fake_categories(texts: dict[str, str]) -> list[str]:
    joined = "\n".join([*texts.keys(), *texts.values()]).lower()
    categories: list[str] = []
    if any(term in joined for term in ["model", "provider"]):
        categories.append("Model configuration")
    if any(term in joined for term in ["billing", "invoice", "subscription"]):
        categories.append("Billing")
    if any(term in joined for term in ["release", "release notes", "release-notes"]):
        categories.append("Release notes")
    if any(term in joined for term in ["knowledge base", "knowledge-base"]):
        categories.append("Knowledge base")
    return categories or ["Repository documentation"]


def fake_project_structure(paths: Iterable[str]) -> list[str]:
    roots: dict[str, int] = {}
    for path in paths:
        root = path.split("/", maxsplit=1)[0]
        if root:
            roots[root] = roots.get(root, 0) + 1
    return [
        f"{root}/: {count} selected evidence file{'s' if count != 1 else ''}"
        for root, count in sorted(roots.items())
    ][:12]


def fake_domain_terms(texts: Iterable[str]) -> list[str]:
    joined = "\n".join(texts).lower()
    candidates = re.findall(r"\b[a-z][a-z0-9]+(?:[-_ ][a-z0-9]+){1,3}\b", joined)
    return unique_terms(term.replace("_", "-").strip() for term in candidates)[:12]


def markdown_bullets(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values if value.strip())


def unique_terms(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result
