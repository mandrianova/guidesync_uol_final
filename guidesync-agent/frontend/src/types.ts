export type PageId = "projects" | "settings" | "run" | "reports" | "app-settings";

export type ProviderKind = "mock" | "pydantic_ai" | "local_http";
export type RunMode = "default_branch_period" | "select_branches";
export type KnowledgeIndexStatus = "queued" | "running" | "completed" | "failed";

export interface ProjectRepository {
  id: string;
  name: string;
  url: string;
  default_branch: string | null;
  paths: string[];
}

export interface ProjectDocumentation {
  id: string;
  name: string;
  description: string | null;
  content: string;
}

export interface ProjectConfig {
  id: string | null;
  name: string;
  description: string | null;
  repositories: ProjectRepository[];
  documentation: ProjectDocumentation[];
  created_at?: string;
  updated_at?: string;
}

export interface ProjectCreate {
  name: string;
  description: string | null;
  repositories: ProjectRepository[];
  documentation: ProjectDocumentation[];
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
}

export interface ModelSettingsUpdate {
  name: string | null;
  provider: ProviderKind;
  model: string;
  base_url?: string | null;
  api_key?: string;
  clear_api_key: boolean;
  timeout_seconds: number;
}

export interface ProjectRunRequest {
  mode: RunMode;
  goal: string;
  since: string | null;
  until: string | null;
  branches: Record<string, string[]>;
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
  nodes: number;
  edges: number;
  chunks: number;
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
