import type {
  BranchListResponse,
  GuideSyncRunResult,
  KnowledgeDocumentRefs,
  KnowledgeIndexRun,
  KnowledgeSearchResult,
  KnowledgeTag,
  ModelSettings,
  ModelSettingsUpdate,
  ProjectConfig,
  ProjectCreate,
  ProjectProfileSnapshot,
  ProjectRepository,
  ProjectRunRequest,
  RunSummary
} from "../types";

const apiBaseUrl = (import.meta.env.VITE_GUIDESYNC_API_BASE_URL || "").replace(/\/$/, "");

function apiUrl(path: string): string {
  return `${apiBaseUrl}${path}`;
}

async function requestJson<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(apiUrl(url), {
    credentials: "include",
    headers: { "content-type": "application/json", ...options.headers },
    ...options
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status}: ${body}`);
  }
  return response.json() as Promise<T>;
}

export async function requestText(url: string): Promise<string> {
  const response = await fetch(apiUrl(url), { credentials: "include" });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status}: ${body}`);
  }
  return response.text();
}

export function artifactUrl(
  runId: string,
  filename: string,
  params: Record<string, string> = {}
): string {
  const query = new URLSearchParams(params).toString();
  return `${apiBaseUrl}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(filename)}${
    query ? `?${query}` : ""
  }`;
}

export const api = {
  listProjects: () => requestJson<ProjectConfig[]>("/projects"),
  getProject: (projectId: string) => requestJson<ProjectConfig>(`/projects/${projectId}`),
  createProject: (project: ProjectCreate) =>
    requestJson<ProjectConfig>("/projects", {
      method: "POST",
      body: JSON.stringify(project)
    }),
  updateProject: (projectId: string, project: ProjectCreate) =>
    requestJson<ProjectConfig>(`/projects/${projectId}`, {
      method: "PUT",
      body: JSON.stringify(project)
    }),
  getProjectProfile: (projectId: string) =>
    requestJson<ProjectProfileSnapshot>(`/projects/${encodeURIComponent(projectId)}/profile`),
  rebuildProjectProfile: (projectId: string) =>
    requestJson<ProjectProfileSnapshot>(`/projects/${encodeURIComponent(projectId)}/profile`, {
      method: "POST"
    }),
  syncRepository: (projectId: string, repositoryId: string) =>
    requestJson<ProjectRepository>(
      `/projects/${encodeURIComponent(projectId)}/repositories/${encodeURIComponent(repositoryId)}/sync`,
      { method: "POST" }
    ),
  listModelProfiles: () => requestJson<ModelSettings[]>("/settings/models"),
  createModelProfile: (settings: ModelSettingsUpdate) =>
    requestJson<ModelSettings>("/settings/models", {
      method: "POST",
      body: JSON.stringify(settings)
    }),
  updateModelProfile: (profileId: string, settings: ModelSettingsUpdate) =>
    requestJson<ModelSettings>(`/settings/models/${profileId}`, {
      method: "PUT",
      body: JSON.stringify(settings)
    }),
  setDefaultModelProfile: (profileId: string) =>
    requestJson<ModelSettings>(`/settings/models/${profileId}/default`, { method: "PUT" }),
  deleteModelProfile: (profileId: string) =>
    requestJson<ModelSettings>(`/settings/models/${profileId}`, { method: "DELETE" }),
  listProjectRuns: (projectId: string) =>
    requestJson<RunSummary[]>(`/projects/${projectId}/runs`),
  createProjectRun: (projectId: string, request: ProjectRunRequest) =>
    requestJson<RunSummary>(`/projects/${projectId}/runs`, {
      method: "POST",
      body: JSON.stringify(request)
    }),
  getRun: (runId: string) => requestJson<GuideSyncRunResult>(`/runs/${runId}`),
  listKnowledgeRuns: (projectId: string) =>
    requestJson<KnowledgeIndexRun[]>(`/projects/${projectId}/knowledge/index-runs`),
  createKnowledgeRun: (projectId: string, maxFiles: number) =>
    requestJson<KnowledgeIndexRun>(`/projects/${projectId}/knowledge/index-runs`, {
      method: "POST",
      body: JSON.stringify({ max_files: maxFiles })
    }),
  listKnowledgeDocuments: (projectId: string) =>
    requestJson<KnowledgeDocumentRefs>(`/projects/${projectId}/knowledge/documents`),
  listKnowledgeTags: (projectId: string) =>
    requestJson<KnowledgeTag[]>(`/projects/${projectId}/knowledge/tags`),
  searchKnowledge: (projectId: string, query: string, limit = 8) =>
    requestJson<KnowledgeSearchResult[]>(`/projects/${projectId}/knowledge/search`, {
      method: "POST",
      body: JSON.stringify({ query, limit })
    }),
  listBranches: (projectId: string, repositoryId: string) =>
    requestJson<BranchListResponse>(
      `/projects/${encodeURIComponent(projectId)}/repositories/${encodeURIComponent(repositoryId)}/branches`
    )
};
