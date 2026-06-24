import type { ProjectConfig, ProjectCreate, ProjectRepository } from "../types";

export function uid(prefix: string): string {
  return `${prefix}-${crypto.randomUUID().slice(0, 10)}`;
}

export function blankProject(): ProjectConfig {
  return {
    id: null,
    name: "Untitled release notes project",
    description: "",
    repositories: [
      {
        id: uid("repo"),
        name: "repository",
        url: "https://github.com/pydantic/pydantic-ai",
        default_branch: "main",
        paths: []
      }
    ],
    documentation: [
      {
        id: "doc-primary",
        name: "product-context",
        description: "Editable product context stored in the database.",
        content:
          "Describe the intended user-facing product area, current assumptions, terminology, and known release-note constraints here."
      }
    ]
  };
}

export function cloneProject(project: ProjectConfig): ProjectConfig {
  return structuredClone(project);
}

export function projectPayload(project: ProjectConfig): ProjectCreate {
  return {
    name: project.name.trim(),
    description: project.description?.trim() || null,
    repositories: project.repositories
      .map((repository) => ({
        ...repository,
        name: repository.name.trim(),
        url: repository.url.trim(),
        default_branch: repository.default_branch?.trim() || null,
        paths: repository.paths.map((path) => path.trim()).filter(Boolean)
      }))
      .filter((repository) => repository.name && repository.url),
    documentation: [
      {
        id: project.documentation[0]?.id || "doc-primary",
        name: project.documentation[0]?.name || "product-context",
        description: "Editable product context stored in the database.",
        content: project.documentation[0]?.content || ""
      }
    ]
  };
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
