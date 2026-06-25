export type PageId = "projects" | "settings" | "knowledge" | "run" | "reports" | "app-settings";

export type ProviderKind = "mock" | "pydantic_ai" | "local_http";
export type RunMode = "default_branch_period" | "select_branches";
export type Audience = "developers" | "end_users" | "business_analysts";
export type ScreenshotPolicy = "disabled" | "optional" | "required";
export type RepositoryCacheStatus = "not_synced" | "syncing" | "ready" | "failed";
export type KnowledgeIndexStatus = "queued" | "running" | "completed" | "failed";
export type ProjectProfileStatus = "queued" | "running" | "completed" | "failed";
export type ModelThinking = boolean | "minimal" | "low" | "medium" | "high" | "xhigh";

export interface ProjectRepository {
  id: string;
  name: string;
  url: string;
  default_branch: string | null;
  analysis_paths: string[];
  paths?: string[];
  credential_ref: string | null;
  cache_status: RepositoryCacheStatus;
  local_path: string | null;
  current_commit: string | null;
  cache_warnings: string[];
}

export interface ProjectDocumentation {
  id: string;
  name: string;
  description: string | null;
  path: string | null;
}

export interface ProjectConfig {
  id: string | null;
  name: string;
  description: string | null;
  audience: Audience;
  documentation_instructions: string;
  knowledge_base_repository_id: string | null;
  knowledge_base_ref: string | null;
  knowledge_base_path: string;
  analysis_paths: string[];
  credential_ref: string | null;
  repositories: ProjectRepository[];
  documentation: ProjectDocumentation[];
  created_at?: string;
  updated_at?: string;
}

export interface ProjectCreate {
  name: string;
  description: string | null;
  audience: Audience;
  documentation_instructions: string;
  knowledge_base_repository_id: string | null;
  knowledge_base_ref: string | null;
  knowledge_base_path: string;
  analysis_paths: string[];
  credential_ref: string | null;
  repositories: ProjectRepository[];
  documentation: ProjectDocumentation[];
}

export interface ProjectProfileRepositoryMapItem {
  repository_id: string;
  name: string;
  url: string;
  default_branch: string | null;
  current_commit: string | null;
  cache_status: RepositoryCacheStatus;
  analysis_paths: string[];
  knowledge_base_path: string | null;
}

export interface ProjectProfileSourceRef {
  repository_id: string;
  repository_name: string;
  ref: string | null;
  commit_sha: string | null;
  local_path: string | null;
  docs_path: string | null;
  analysis_paths: string[];
}

export interface ProjectProfileSnapshot {
  id: string;
  project_id: string;
  status: ProjectProfileStatus;
  version: number;
  prompt_version: string;
  summary: string;
  architecture: string[];
  workflows: string[];
  key_terms: string[];
  repository_map: ProjectProfileRepositoryMapItem[];
  source_refs: ProjectProfileSourceRef[];
  warnings: string[];
  uncertainty_notes: string[];
  artifact_uris: Record<string, string>;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface ModelSettings {
  id: string;
  name: string;
  provider: ProviderKind;
  model: string;
  base_url: string | null;
  has_api_key: boolean;
  is_default: boolean;
  timeout_seconds: number;
  thinking: ModelThinking | null;
}

export interface ModelSettingsUpdate {
  name: string | null;
  provider: ProviderKind;
  model: string;
  base_url?: string | null;
  api_key?: string;
  clear_api_key: boolean;
  timeout_seconds: number;
  thinking: ModelThinking | null;
}

export interface ProjectRunRequest {
  mode: RunMode;
  goal: string;
  since: string | null;
  until: string | null;
  branches: Record<string, string[]>;
  audience?: Audience | null;
  task_interface_url?: string | null;
  screenshot_policy?: ScreenshotPolicy;
}

export interface RunSummary {
  run_id: string;
  status: string;
  title: string;
  created_at: string;
  updated_at: string;
  provider: string | null;
  model: string | null;
  artifacts: Record<string, string>;
}

export interface FileChange {
  file: string;
  added?: number | null;
  removed?: number | null;
}

export interface CommitEvidence {
  repo: string;
  sha: string;
  short_sha: string;
  date: string;
  subject: string;
  body: string;
  files: string[];
  file_stats: FileChange[];
  user_facing_score: number;
}

export interface DocumentationEvidence {
  name: string;
  path: string;
  excerpt: string;
}

export interface BrowserScreenshotEvidence {
  scenario: string;
  url: string;
  path: string;
  notes?: string | null;
  created_at: string;
}

export interface EvidenceBundle {
  collected_at: string;
  repositories: string[];
  commits: CommitEvidence[];
  documentation: DocumentationEvidence[];
  browser_screenshots: BrowserScreenshotEvidence[];
  warnings: string[];
}

export interface EvidenceReference {
  source: string;
  detail: string;
  relevance: string;
}

export interface DocumentationUpdate {
  title: string;
  summary: string;
  user_facing_change: string;
  proposed_update_markdown: string;
  evidence_used: EvidenceReference[];
  reviewer_checks: Array<{ name: string; status: string; notes: string }>;
  risks_or_limitations: string[];
  suggested_improvements: string[];
}

export interface ProviderRunMetadata {
  provider: string;
  model: string;
  started_at: string;
  completed_at: string;
  latency_ms: number;
  token_usage: Record<string, unknown>;
  cost: Record<string, unknown>;
  error?: string | null;
}

export interface ValidationFinding {
  severity: string;
  check: string;
  message: string;
}

export interface GuideSyncRunResult {
  run_id: string;
  status: string;
  request: {
    goal: string;
    report?: { title?: string };
  };
  evidence: EvidenceBundle;
  update: DocumentationUpdate | null;
  provider_metadata: ProviderRunMetadata | null;
  findings: ValidationFinding[];
  artifacts: Record<string, string>;
}

export interface KnowledgeIndexSummary {
  repositories: number;
  files: number;
  documentation_sources: number;
  documents: number;
  sections: number;
  nodes: number;
  edges: number;
  chunks: number;
  indexed_commit_sha: string | null;
  previous_indexed_commit_sha: string | null;
  changed_documentation_files: string[];
  warnings: string[];
}

export interface KnowledgeIndexRun {
  id: string;
  project_id: string | null;
  status: KnowledgeIndexStatus;
  source_ref: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  summary: KnowledgeIndexSummary;
}

export interface BranchInfo {
  name: string;
  updated_at: string | null;
}

export interface BranchListResponse {
  branches: BranchInfo[];
  warning?: string | null;
}
