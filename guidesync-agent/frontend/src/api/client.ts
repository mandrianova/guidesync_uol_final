import createClient from "openapi-fetch";

import type { paths } from "./generated/schema";
import type {
  BranchListResponse,
  EvaluationComparisonPage,
  EvaluationExperimentPage,
  EvaluationExperimentRecord,
  EvaluationRunPage,
  GuideSyncRunResult,
  KnowledgeDocumentDetail,
  KnowledgeDocumentRefs,
  KnowledgeIndexRun,
  KnowledgeSearchResult,
  KnowledgeTag,
  LLMConversationTranscript,
  LLMTranscriptSummary,
  ModelCallLedgerEntry,
  ModelSettings,
  ModelSettingsUpdate,
  ProjectConfig,
  ProjectCreate,
  ProjectPipelineState,
  ProjectProfileSnapshot,
  ProjectRepository,
  ProjectRunRequest,
  ProjectWorkflowPlan,
  ProjectWorkflowTask,
  PublicationReport,
  RunCancellationResult,
  RunTokenUsageSummary,
  RunSummary,
  VideoPresentationSummary,
  WorkflowTaskTokenUsageSummary
} from "../types";

const apiBaseUrl = (import.meta.env.VITE_GUIDESYNC_API_BASE_URL || "").replace(/\/$/, "");
const sdk = createClient<paths>({
  baseUrl: apiBaseUrl,
  credentials: "include"
});

function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  return `${apiBaseUrl}${path}`;
}

interface ApiResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

function formatError(error: unknown): string {
  if (typeof error === "string") {
    return error;
  }
  if (error && typeof error === "object") {
    return JSON.stringify(error);
  }
  return "Request failed";
}

async function unwrap<T>(result: ApiResult<unknown> | Promise<ApiResult<unknown>>): Promise<T> {
  const resolved = await result;
  if (resolved.error !== undefined || !resolved.response.ok) {
    throw new Error(`${resolved.response.status}: ${formatError(resolved.error)}`);
  }
  return resolved.data as T;
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
  listProjects: async () => unwrap<ProjectConfig[]>(await sdk.GET("/projects")),
  getProject: async (projectId: string) =>
    unwrap<ProjectConfig>(
      await sdk.GET("/projects/{project_id}", {
        params: { path: { project_id: projectId } }
      })
    ),
  createProject: async (project: ProjectCreate) =>
    unwrap<ProjectConfig>(await sdk.POST("/projects", { body: project })),
  updateProject: async (projectId: string, project: ProjectCreate) =>
    unwrap<ProjectConfig>(
      await sdk.PUT("/projects/{project_id}", {
        params: { path: { project_id: projectId } },
        body: project
      })
    ),
  getProjectProfile: async (projectId: string) =>
    unwrap<ProjectProfileSnapshot>(
      await sdk.GET("/projects/{project_id}/profile", {
        params: { path: { project_id: projectId } }
      })
    ),
  rebuildProjectProfile: async (projectId: string) =>
    unwrap<ProjectProfileSnapshot>(
      await sdk.POST("/projects/{project_id}/profile", {
        params: { path: { project_id: projectId } }
      })
    ),
  listWorkflowTasks: (projectId: string) =>
    unwrap<ProjectWorkflowTask[]>(
      sdk.GET("/projects/{project_id}/workflow/tasks", {
        params: { path: { project_id: projectId } }
      })
    ),
  getWorkflowState: (projectId: string) =>
    unwrap<ProjectPipelineState>(
      sdk.GET("/projects/{project_id}/workflow/state", {
        params: { path: { project_id: projectId } }
      })
    ),
  enqueueProfileRebuild: (projectId: string) =>
    unwrap<ProjectWorkflowPlan>(
      sdk.POST("/projects/{project_id}/workflow/profile", {
        params: { path: { project_id: projectId } }
      })
    ),
  enqueueKnowledgeBuild: (projectId: string) =>
    unwrap<ProjectWorkflowPlan>(
      sdk.POST("/projects/{project_id}/workflow/knowledge", {
        params: { path: { project_id: projectId } }
      })
    ),
  enqueueAnalysisPipeline: (projectId: string, request: ProjectRunRequest) =>
    unwrap<ProjectWorkflowPlan>(
      sdk.POST("/projects/{project_id}/workflow/run-analysis", {
        params: { path: { project_id: projectId } },
        body: {
          ...request,
          screenshot_policy: request.screenshot_policy ?? "disabled"
        }
      })
    ),
  syncRepository: (projectId: string, repositoryId: string) =>
    unwrap<ProjectRepository>(
      sdk.POST("/projects/{project_id}/repositories/{repository_id}/sync", {
        params: { path: { project_id: projectId, repository_id: repositoryId } }
      })
    ),
  getRepositoryStatus: (projectId: string, repositoryId: string) =>
    unwrap<ProjectRepository>(
      sdk.GET("/projects/{project_id}/repositories/{repository_id}/status", {
        params: { path: { project_id: projectId, repository_id: repositoryId } }
      })
    ),
  listModelProfiles: async () => unwrap<ModelSettings[]>(await sdk.GET("/settings/models")),
  createModelProfile: (settings: ModelSettingsUpdate) =>
    unwrap<ModelSettings>(sdk.POST("/settings/models", { body: settings })),
  updateModelProfile: (profileId: string, settings: ModelSettingsUpdate) =>
    unwrap<ModelSettings>(
      sdk.PUT("/settings/models/{profile_id}", {
        params: { path: { profile_id: profileId } },
        body: settings
      })
    ),
  setDefaultModelProfile: (profileId: string) =>
    unwrap<ModelSettings>(
      sdk.PUT("/settings/models/{profile_id}/default", {
        params: { path: { profile_id: profileId } }
      })
    ),
  deleteModelProfile: (profileId: string) =>
    unwrap<ModelSettings>(
      sdk.DELETE("/settings/models/{profile_id}", {
        params: { path: { profile_id: profileId } }
      })
    ),
  listProjectRuns: (projectId: string) =>
    unwrap<RunSummary[]>(
      sdk.GET("/projects/{project_id}/runs", {
        params: { path: { project_id: projectId } }
      })
    ),
  createProjectRun: (projectId: string, request: ProjectRunRequest) =>
    unwrap<RunSummary>(
      sdk.POST("/projects/{project_id}/runs", {
        params: { path: { project_id: projectId } },
        body: {
          ...request,
          screenshot_policy: request.screenshot_policy ?? "disabled"
        }
      })
    ),
  getRun: (runId: string) =>
    unwrap<GuideSyncRunResult>(
      sdk.GET("/runs/{run_id}", {
        params: { path: { run_id: runId } }
      })
    ),
  getPublicationReport: (runId: string) =>
    unwrap<PublicationReport>(
      sdk.GET("/runs/{run_id}/publication-report", {
        params: { path: { run_id: runId } }
      })
    ),
  getVideoPresentation: (runId: string) =>
    unwrap<VideoPresentationSummary>(
      sdk.GET("/runs/{run_id}/video-presentation", {
        params: { path: { run_id: runId } }
      })
    ),
  generateVideoPresentation: (runId: string, regenerate = false) =>
    unwrap<VideoPresentationSummary>(
      sdk.POST("/runs/{run_id}/video-presentation", {
        params: { path: { run_id: runId } },
        body: { regenerate }
      })
    ),
  cancelRun: (runId: string) =>
    unwrap<RunCancellationResult>(
      sdk.POST("/runs/{run_id}/cancel", {
        params: { path: { run_id: runId } }
      })
    ),
  listEvaluationExperiments: (projectId: string, limit = 20, offset = 0) =>
    unwrap<EvaluationExperimentPage>(
      sdk.GET("/projects/{project_id}/evaluations/experiments", {
        params: { path: { project_id: projectId }, query: { limit, offset } }
      })
    ),
  getEvaluationExperiment: (experimentId: string) =>
    unwrap<EvaluationExperimentRecord>(
      sdk.GET("/evaluations/experiments/{experiment_id}", {
        params: { path: { experiment_id: experimentId } }
      })
    ),
  listEvaluationRuns: (
    experimentId: string,
    filters: {
      caseId?: string;
      conditionId?: string;
      status?: "completed" | "failed";
      limit?: number;
      offset?: number;
    } = {}
  ) =>
    unwrap<EvaluationRunPage>(
      sdk.GET("/evaluations/experiments/{experiment_id}/runs", {
        params: {
          path: { experiment_id: experimentId },
          query: {
            case_id: filters.caseId,
            condition_id: filters.conditionId,
            status: filters.status,
            limit: filters.limit ?? 100,
            offset: filters.offset ?? 0
          }
        }
      })
    ),
  listEvaluationComparisons: (experimentId: string, limit = 100, offset = 0) =>
    unwrap<EvaluationComparisonPage>(
      sdk.GET("/evaluations/experiments/{experiment_id}/comparisons", {
        params: {
          path: { experiment_id: experimentId },
          query: { limit, offset }
        }
      })
    ),
  listRunModelUsage: (runId: string, limit = 100, offset = 0) =>
    unwrap<ModelCallLedgerEntry[]>(
      sdk.GET("/runs/{run_id}/model-usage", {
        params: { path: { run_id: runId }, query: { limit, offset } }
      })
    ),
  getRunModelUsageSummary: (runId: string) =>
    unwrap<RunTokenUsageSummary>(
      sdk.GET("/runs/{run_id}/model-usage/summary", {
        params: { path: { run_id: runId } }
      })
    ),
  getWorkflowTaskModelUsageSummary: (workflowTaskId: string) =>
    unwrap<WorkflowTaskTokenUsageSummary>(
      sdk.GET("/workflow-tasks/{workflow_task_id}/model-usage/summary", {
        params: { path: { workflow_task_id: workflowTaskId } }
      })
    ),
  listRunLlmTranscripts: (runId: string) =>
    unwrap<LLMTranscriptSummary[]>(
      sdk.GET("/runs/{run_id}/llm-transcripts", {
        params: { path: { run_id: runId } }
      })
    ),
  listWorkflowTaskLlmTranscripts: (workflowTaskId: string) =>
    unwrap<LLMTranscriptSummary[]>(
      sdk.GET("/workflow-tasks/{workflow_task_id}/llm-transcripts", {
        params: { path: { workflow_task_id: workflowTaskId } }
      })
    ),
  getLlmTranscript: (transcriptId: string) =>
    unwrap<LLMConversationTranscript>(
      sdk.GET("/llm-transcripts/{transcript_id}", {
        params: { path: { transcript_id: transcriptId } }
      })
    ),
  getLlmTranscriptArtifact: (transcriptId: string) =>
    unwrap<LLMConversationTranscript>(
      sdk.GET("/llm-transcripts/{transcript_id}/artifact", {
        params: { path: { transcript_id: transcriptId } }
      })
    ),
  listKnowledgeRuns: (projectId: string) =>
    unwrap<KnowledgeIndexRun[]>(
      sdk.GET("/projects/{project_id}/knowledge/index-runs", {
        params: { path: { project_id: projectId } }
      })
    ),
  createKnowledgeRun: (projectId: string) =>
    unwrap<KnowledgeIndexRun>(
      sdk.POST("/projects/{project_id}/knowledge/index-runs", {
        params: { path: { project_id: projectId } }
      })
    ),
  listKnowledgeDocuments: (projectId: string) =>
    unwrap<KnowledgeDocumentRefs>(
      sdk.GET("/projects/{project_id}/knowledge/documents", {
        params: { path: { project_id: projectId } }
      })
    ),
  getKnowledgeDocumentDetail: (projectId: string, documentId: string) =>
    unwrap<KnowledgeDocumentDetail>(
      sdk.GET("/projects/{project_id}/knowledge/documents/{document_id}", {
        params: { path: { project_id: projectId, document_id: documentId } }
      })
    ),
  listKnowledgeTags: (projectId: string) =>
    unwrap<KnowledgeTag[]>(
      sdk.GET("/projects/{project_id}/knowledge/tags", {
        params: { path: { project_id: projectId } }
      })
    ),
  searchKnowledge: (projectId: string, query: string, limit = 8) =>
    unwrap<KnowledgeSearchResult[]>(
      sdk.POST("/projects/{project_id}/knowledge/search", {
        params: { path: { project_id: projectId } },
        body: { query, limit, include_diagnostics: true }
      })
    ),
  listBranches: (projectId: string, repositoryId: string) =>
    unwrap<BranchListResponse>(
      sdk.GET("/projects/{project_id}/repositories/{repository_id}/branches", {
        params: { path: { project_id: projectId, repository_id: repositoryId } }
      })
    )
};

export function publicReportUrl(runId: string, print = false): string {
  const route = `/reports/${encodeURIComponent(runId)}/public`;
  return `#${route}${print ? "?print=1" : ""}`;
}
