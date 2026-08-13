import type { Audience, ProjectConfig, ProjectCreate, ProjectProfileStatus, ProjectRepository } from "../types";

export function uid(prefix: string): string {
  const randomUUID = globalThis.crypto?.randomUUID;
  if (typeof randomUUID === "function") {
    return `${prefix}-${randomUUID.call(globalThis.crypto).slice(0, 10)}`;
  }
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(5));
  const fragment = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${prefix}-${fragment}`;
}

export function blankProject(): ProjectConfig {
  const repositoryId = uid("repo");
  return {
    id: null,
    name: "Untitled release notes project",
    description: "",
    audience: "end_users",
    documentation_instructions:
      "Write documentation updates that are traceable to repository evidence and useful for the selected audience.",
    knowledge_base_repository_id: repositoryId,
    knowledge_base_ref: "main",
    knowledge_base_path: "docs/",
    analysis_paths: ["docs/", "src/"],
    credential_ref: null,
    task_interface_url: null,
    repositories: [
      {
        id: repositoryId,
        name: "repository",
        url: "https://github.com/pydantic/pydantic-ai",
        default_branch: "main",
        analysis_paths: ["docs/", "src/"],
        credential_ref: null,
        cache_status: "not_synced",
        local_path: null,
        current_commit: null,
        cache_warnings: []
      }
    ],
    documentation: []
  };
}

export function cloneProject(project: ProjectConfig): ProjectConfig {
  return structuredClone(project);
}

export function projectPayload(project: ProjectConfig): ProjectCreate {
  const analysisPaths = cleanPaths(project.analysis_paths);
  const repositories = project.repositories
    .map((repository) => {
      const repositoryAnalysisPaths = cleanPaths(repository.analysis_paths);
      return {
        ...repository,
        name: repository.name.trim(),
        url: repository.url.trim(),
        default_branch: repository.default_branch?.trim() || null,
        analysis_paths: repositoryAnalysisPaths.length ? repositoryAnalysisPaths : analysisPaths,
        credential_ref: repository.credential_ref?.trim() || null,
        cache_status: repository.cache_status || "not_synced",
        local_path: repository.local_path || null,
        current_commit: repository.current_commit || null,
        cache_warnings: repository.cache_warnings || []
      };
    })
    .filter((repository) => repository.name && repository.url);
  const selectedKnowledgeRepository = repositories.some(
    (repository) => repository.id === project.knowledge_base_repository_id
  )
    ? project.knowledge_base_repository_id
    : repositories[0]?.id || null;
  const knowledgeRepository = repositories.find(
    (repository) => repository.id === selectedKnowledgeRepository
  );
  return {
    name: project.name.trim(),
    description: project.description?.trim() || null,
    audience: project.audience,
    documentation_instructions: project.documentation_instructions.trim(),
    knowledge_base_repository_id: selectedKnowledgeRepository,
    knowledge_base_ref: project.knowledge_base_ref?.trim() || knowledgeRepository?.default_branch || null,
    knowledge_base_path: project.knowledge_base_path.trim(),
    analysis_paths: analysisPaths,
    credential_ref: project.credential_ref?.trim() || null,
    task_interface_url: project.task_interface_url?.trim() || null,
    repositories,
    documentation: project.documentation
      .map((document) => ({
        id: document.id,
        name: document.name.trim(),
        description: document.description?.trim() || null,
        path: document.path?.trim() || null
      }))
      .filter((document) => document.name && document.path)
  };
}

export function cleanPaths(paths: string[]): string[] {
  return paths.map((path) => path.trim()).filter(Boolean);
}

export function audienceLabel(audience: Audience): string {
  const labels: Record<Audience, string> = {
    business_analysts: "Business analysts",
    developers: "Developers",
    end_users: "End users"
  };
  return labels[audience];
}

export function repositoryCacheStatusLabel(repository: ProjectRepository): string {
  const labels: Record<ProjectRepository["cache_status"], string> = {
    failed: "Sync failed",
    not_synced: "Not synced",
    ready: "Ready",
    syncing: "Syncing"
  };
  return labels[repository.cache_status || "not_synced"];
}

export function profileStatusLabel(status: ProjectProfileStatus): string {
  const labels: Record<ProjectProfileStatus, string> = {
    cancelled: "Profile stopped",
    completed: "Profile ready",
    failed: "Profile failed",
    queued: "Profile queued",
    running: "Profile running"
  };
  return labels[status];
}

export function repositoryCountLabel(count: number): string {
  return `${count} ${count === 1 ? "repo" : "repos"}`;
}

export function readableRepositoryLabel(repository: ProjectRepository): string {
  const name = repository.name.trim();
  if (name && name.toLowerCase() !== "repository") {
    return name;
  }
  try {
    const url = new URL(repository.url || name);
    const pathParts = url.pathname.split("/").filter(Boolean);
    if (pathParts.length >= 2) {
      return pathParts.slice(0, 2).join("/");
    }
  } catch {
    return repository.url || name || "Repository";
  }
  return repository.url || name || "Repository";
}

export function filterProjects(
  projects: ProjectConfig[],
  query: string
): ProjectConfig[] {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) {
    return projects;
  }
  return projects.filter((project) =>
    project.name.toLocaleLowerCase().includes(normalized)
  );
}

export function resolveProjectSelection(
  projects: ProjectConfig[],
  selectedProjectId: string | null
): ProjectConfig | null {
  return (
    projects.find((project) => project.id === selectedProjectId) ||
    projects[0] ||
    null
  );
}
