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
    ProjectProfileFileListing,
    ProjectProfileFileSelection,
    ProjectProfileRepositoryMapItem,
    ProjectProfileSelectedFile,
    ProjectProfileSourceRef,
    ProjectTaxonomy,
    ProjectTaxonomyEvidenceKind,
    ProjectTaxonomyEvidenceRef,
    RepositoryFileWindow,
)
from guidesync_agent.schemas.project import ProjectProfileEvidenceRef
from guidesync_agent.tools.project_profile import evidence_ref


class FakeProjectProfileAgentProvider:
    provider = "fake"
    model = "fixture-agent"

    def next_action(self, context: AgentLoopPromptContext) -> AgentLoopModelAction:
        request = ProjectProfileAgentRequest.model_validate(context.request.context)
        repository_id = request.repositories[0].repository_id if request.repositories else ""
        if not observations_for(context.observations, AgentLoopToolName.LIST_REPOSITORY_FILES):
            return AgentLoopModelAction(
                action=AgentLoopActionType.TOOL_CALL,
                tool_call=AgentLoopToolCall(
                    tool_name=AgentLoopToolName.LIST_REPOSITORY_FILES,
                    arguments={"repository_id": repository_id, "offset": 0, "limit": 400},
                    reason="fixture provider starts by listing repository files",
                ),
            )

        selected_paths = selected_fixture_paths(context.observations)
        read_paths = {
            str(observation.payload.get("path"))
            for observation in observations_for(
                context.observations,
                AgentLoopToolName.READ_REPOSITORY_FILE,
            )
        }
        next_path = next((path for path in selected_paths if path not in read_paths), None)
        if next_path is not None:
            return AgentLoopModelAction(
                action=AgentLoopActionType.TOOL_CALL,
                tool_call=AgentLoopToolCall(
                    tool_name=AgentLoopToolName.READ_REPOSITORY_FILE,
                    arguments={
                        "repository_id": repository_id,
                        "path": next_path,
                        "offset": 0,
                        "limit": 16_000,
                    },
                    reason="fixture provider reads high-signal project evidence",
                ),
            )

        next_directory = next_fixture_directory_to_expand(context.observations)
        if next_directory is not None:
            return AgentLoopModelAction(
                action=AgentLoopActionType.TOOL_CALL,
                tool_call=AgentLoopToolCall(
                    tool_name=AgentLoopToolName.LIST_REPOSITORY_FILES,
                    arguments={
                        "repository_id": repository_id,
                        "path_filters": [next_directory],
                        "offset": 0,
                        "limit": 400,
                    },
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
        evidence_by_path = {
            window.path: evidence_ref(window.repository_id, window.path)
            for window in evidence.file_windows
            if window.ok
        }
        headings = extract_headings(texts.values())
        architecture = headings[:6] or ["Repository-backed documentation workflow"]
        components = extract_components(texts.keys(), texts.values())
        categories = fake_categories(texts)
        workflows = fake_workflows(headings, texts.values())
        domain_terms = fake_domain_terms(texts.values())
        project_structure = fake_project_structure(texts.keys())
        core_concepts = unique_terms([*categories, *components, *workflows, *domain_terms])[:16]
        project_description = (
            f"{request.name} is profiled from repository evidence"
            f" across {len(texts)} selected files."
        )
        agent_context = fake_agent_context(
            project_description,
            project_structure,
            architecture,
            workflows,
            core_concepts,
        )
        documentation_areas = [
            value for value in categories if "release" in value or "doc" in value
        ]
        profile_evidence = [
            ProjectProfileEvidenceRef(
                repository_id=window.repository_id,
                path=window.path,
                reason="fixture provider read this file for project profile evidence",
            )
            for window in evidence.file_windows
            if window.ok
        ]
        return ProjectProfileAgentOutput(
            summary=f"{request.name} profile generated from repository evidence.",
            project_description=project_description,
            project_structure=project_structure,
            architecture=architecture,
            core_concepts=core_concepts,
            workflows=workflows,
            key_terms=unique_terms([*categories, *components, *domain_terms])[:12],
            agent_context=agent_context,
            taxonomy=ProjectTaxonomy(
                version=f"{request.profile_id}:v1",
                confidence=0.75 if profile_evidence else 0.35,
                categories=categories,
                components=components,
                workflows=workflows,
                documentation_areas=documentation_areas,
                domain_terms=domain_terms,
                evidence_refs=taxonomy_evidence_refs(
                    categories,
                    components,
                    workflows,
                    documentation_areas,
                    domain_terms,
                    evidence_by_path,
                ),
                uncertainty_notes=[] if profile_evidence else ["No repository files were read."],
            ),
            profile_evidence=profile_evidence,
            repository_map=[
                ProjectProfileRepositoryMapItem(
                    repository_id=repo.repository_id,
                    name=repo.name,
                    url=repo.url,
                    default_branch=repo.default_branch,
                    current_commit=repo.current_commit,
                    cache_status=repo.cache_status,
                    analysis_paths=repo.analysis_paths,
                    knowledge_base_path=repo.knowledge_base_path,
                )
                for repo in request.repositories
            ],
            source_refs=[
                ProjectProfileSourceRef(
                    repository_id=repo.repository_id,
                    repository_name=repo.name,
                    ref=request.knowledge_base_ref or repo.default_branch,
                    commit_sha=repo.current_commit,
                    docs_path=repo.knowledge_base_path,
                    analysis_paths=repo.analysis_paths,
                )
                for repo in request.repositories
            ],
            warnings=[],
            uncertainty_notes=[] if profile_evidence else ["No repository evidence available."],
            model_metadata={"fixture": True},
        )


def observations_for(
    observations: list[AgentLoopObservation],
    tool_name: AgentLoopToolName,
) -> list[AgentLoopObservation]:
    return [observation for observation in observations if observation.tool_name == tool_name]


def selected_fixture_paths(observations: list[AgentLoopObservation]) -> list[str]:
    files = []
    for observation in observations_for(observations, AgentLoopToolName.LIST_REPOSITORY_FILES):
        raw_files = observation.payload.get("files")
        if isinstance(raw_files, list):
            files.extend(
                item
                for item in raw_files
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            )
    scored = sorted(
        files,
        key=lambda item: (-fake_file_score(str(item["path"])), str(item["path"])),
    )
    return [str(item["path"]) for item in scored[:8]]


def next_fixture_directory_to_expand(
    observations: list[AgentLoopObservation],
) -> str | None:
    expanded = set()
    directories = []
    for observation in observations_for(observations, AgentLoopToolName.LIST_REPOSITORY_FILES):
        path_filters = observation.arguments.get("path_filters")
        if isinstance(path_filters, list):
            expanded.update(str(path) for path in path_filters)
        raw_directories = observation.payload.get("directories")
        if isinstance(raw_directories, list):
            directories.extend(
                item
                for item in raw_directories
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            )
    scored = sorted(
        directories,
        key=lambda item: (-fake_file_score(str(item["path"])), str(item["path"])),
    )
    return next((str(item["path"]) for item in scored if str(item["path"]) not in expanded), None)


def fake_evidence_from_observations(
    observations: list[AgentLoopObservation],
) -> ProjectProfileAgentEvidence:
    listings = [
        ProjectProfileFileListing.model_validate(observation.payload)
        for observation in observations_for(observations, AgentLoopToolName.LIST_REPOSITORY_FILES)
    ]
    windows = [
        RepositoryFileWindow.model_validate(observation.payload)
        for observation in observations_for(observations, AgentLoopToolName.READ_REPOSITORY_FILE)
    ]
    return ProjectProfileAgentEvidence(file_listings=listings, file_windows=windows)


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
        categories.append("model-configuration")
    if any(term in joined for term in ["billing", "invoice", "subscription"]):
        categories.append("billing")
    if any(term in joined for term in ["release notes", "release-notes"]):
        categories.append("release-notes")
    if any(term in joined for term in ["knowledge base", "knowledge-base"]):
        categories.append("knowledge-base")
    return categories or ["repository-documentation"]


def fake_workflows(headings: list[str], texts: Iterable[str]) -> list[str]:
    workflows = [heading for heading in headings if "workflow" in heading.lower()]
    joined = "\n".join(texts).lower()
    if "model" in joined:
        workflows.append("model configuration workflow")
    if "release" in joined:
        workflows.append("release review workflow")
    return unique_terms(workflows)[:8] or ["review repository documentation"]


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


def fake_agent_context(
    project_description: str,
    project_structure: list[str],
    architecture: list[str],
    workflows: list[str],
    core_concepts: list[str],
) -> str:
    sections = [
        project_description,
        "Project structure: " + "; ".join(project_structure[:8]),
        "Architecture: " + "; ".join(architecture[:8]),
        "Workflows: " + "; ".join(workflows[:8]),
        "Core concepts: " + "; ".join(core_concepts[:12]),
    ]
    return "\n".join(section for section in sections if section.strip())


def fake_domain_terms(texts: Iterable[str]) -> list[str]:
    joined = "\n".join(texts).lower()
    candidates = re.findall(r"\b[a-z][a-z0-9]+(?:[-_ ][a-z0-9]+){1,3}\b", joined)
    return unique_terms(term.replace("_", "-").strip() for term in candidates)[:12]


def taxonomy_evidence_refs(
    categories: list[str],
    components: list[str],
    workflows: list[str],
    documentation_areas: list[str],
    domain_terms: list[str],
    evidence_by_path: dict[str, str],
) -> list[ProjectTaxonomyEvidenceRef]:
    refs = list(evidence_by_path.values())[:3]
    items: list[ProjectTaxonomyEvidenceRef] = []
    for kind, values in [
        (ProjectTaxonomyEvidenceKind.CATEGORY, categories),
        (ProjectTaxonomyEvidenceKind.COMPONENT, components),
        (ProjectTaxonomyEvidenceKind.WORKFLOW, workflows),
        (ProjectTaxonomyEvidenceKind.DOCUMENTATION_AREA, documentation_areas),
        (ProjectTaxonomyEvidenceKind.DOMAIN_TERM, domain_terms),
    ]:
        items.extend(
            ProjectTaxonomyEvidenceRef(
                value=value,
                kind=kind,
                reason="fixture provider derived this value from selected repository files",
                evidence_refs=refs,
            )
            for value in values
        )
    return items


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
