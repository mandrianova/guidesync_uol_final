import type { components } from "./api/generated/schema";

type Schemas = components["schemas"];
type Present<T, K extends keyof T> = Omit<T, K> & { [P in K]-?: Exclude<T[P], undefined> };
type Defaults<T, K extends keyof T> = Omit<T, K> & { [P in K]-?: NonNullable<T[P]> };

export type PageId =
  | "projects"
  | "settings"
  | "profile"
  | "knowledge"
  | "run"
  | "reports"
  | "app-settings";

export type ProviderKind = Schemas["ProviderKind"];
export type RunMode = Schemas["RunMode"];
export type Audience = Schemas["Audience"];
export type ScreenshotPolicy = Schemas["ScreenshotPolicy"];
export type RepositoryCacheStatus = Schemas["RepositoryCacheStatus"];
export type KnowledgeIndexStatus = Schemas["KnowledgeIndexStatus"];
export type ProjectProfileStatus = Schemas["ProjectProfileStatus"];
export type ModelRole = Schemas["ModelRole"];
export type ModelThinking = NonNullable<Schemas["ModelSettings"]["thinking"]>;

export type ProjectRepositoryInput = Defaults<
  Present<Schemas["ProjectRepository-Input"], "id">,
  "analysis_paths" | "cache_status" | "cache_warnings"
>;

export type ProjectRepository = Omit<
  Defaults<Present<Schemas["ProjectRepository-Output"], "id">, "analysis_paths" | "cache_status" | "cache_warnings">,
  "paths"
> & {
  paths?: string[];
};

export type ProjectDocumentation = Present<Schemas["ProjectDocumentation"], "id">;

export type ProjectConfig = Omit<
  Defaults<Present<Schemas["ProjectConfig"], "id">, "analysis_paths" | "documentation" | "repositories">,
  "documentation" | "id" | "repositories"
> & {
  documentation: ProjectDocumentation[];
  id: string | null;
  repositories: ProjectRepository[];
};

export type ProjectCreate = Omit<
  Defaults<Schemas["ProjectCreate"], "analysis_paths" | "documentation" | "repositories">,
  "documentation" | "repositories"
> & {
  documentation: ProjectDocumentation[];
  repositories: ProjectRepositoryInput[];
};

export type ProjectProfileRepositoryMapItem = Defaults<
  Schemas["ProjectProfileRepositoryMapItem"],
  "analysis_paths" | "cache_status"
>;
export type ProjectProfileSourceRef = Defaults<Schemas["ProjectProfileSourceRef"], "analysis_paths">;

export type ProjectTaxonomy = Defaults<
  Schemas["ProjectTaxonomy"],
  | "aliases"
  | "audience_terms"
  | "bootstrap_hints"
  | "candidate_terms"
  | "categories"
  | "components"
  | "documentation_areas"
  | "domain_terms"
  | "evidence_refs"
  | "uncertainty_notes"
  | "workflows"
>;

export type ProjectProfileSnapshot = Omit<
  Defaults<
    Present<Schemas["ProjectProfileSnapshot"], "id" | "created_at">,
    | "architecture"
    | "agent_context"
    | "artifact_uris"
    | "core_concepts"
    | "key_terms"
    | "model_metadata"
    | "profile_evidence"
    | "project_description"
    | "project_structure"
    | "repository_map"
    | "source_refs"
    | "taxonomy"
    | "tool_trace_refs"
    | "uncertainty_notes"
    | "validation_findings"
    | "warnings"
    | "workflows"
  >,
  "repository_map" | "source_refs" | "taxonomy"
> & {
  repository_map: ProjectProfileRepositoryMapItem[];
  source_refs: ProjectProfileSourceRef[];
  taxonomy: ProjectTaxonomy;
};

export type ProjectWorkflowTaskKind = Schemas["ProjectWorkflowTaskKind"];
export type ProjectWorkflowTaskStatus = Schemas["ProjectWorkflowTaskStatus"];
export type ProjectWorkflowTask = Defaults<
  Present<Schemas["ProjectWorkflowTask"], "id" | "created_at">,
  "depends_on_task_ids" | "warnings"
>;
export type ProjectWorkflowPlan = Omit<
  Defaults<Schemas["ProjectWorkflowPlan"], "tasks" | "warnings">,
  "tasks"
> & {
  tasks: ProjectWorkflowTask[];
};
export type ProjectPipelineState = Omit<Defaults<Schemas["ProjectPipelineState"], "tasks">, "tasks"> & {
  tasks: ProjectWorkflowTask[];
};

export type ModelSettings = Schemas["ModelSettings"];
export type ModelSettingsUpdate = Schemas["ModelSettingsUpdate"];
export type RequestedModelSettings = Defaults<Schemas["RequestedModelSettings"], "metadata">;
export type EffectiveModelConfiguration = Defaults<Schemas["EffectiveModelConfiguration"], "metadata">;

export type ProjectRunRequest = Omit<
  Defaults<Schemas["ProjectRunRequest"], "branches">,
  "requested_model_settings" | "screenshot_policy"
> & {
  requested_model_settings?: RequestedModelSettings | null;
  screenshot_policy?: ScreenshotPolicy;
};

export type RunSummary = Schemas["RunSummary"];
export type ModelCallLedgerEntry = Schemas["ModelCallLedgerEntry"];
export type RunTokenUsageSummary = Schemas["RunTokenUsageSummary"];
export type WorkflowTaskTokenUsageSummary = Schemas["WorkflowTaskTokenUsageSummary"];
export type LLMConversationTranscript = Schemas["LLMConversationTranscript"];
export type LLMTranscriptSummary = Schemas["LLMTranscriptSummary"];

export type FileChange = Schemas["FileChange"];
export type CommitEvidence = Defaults<Schemas["CommitEvidence"], "file_stats" | "files">;
export type DocumentationEvidence = Schemas["DocumentationEvidence"];
export type BrowserScreenshotEvidence = Defaults<
  Schemas["BrowserScreenshotEvidence"],
  "console_errors" | "matched_text" | "missing_text" | "network_errors" | "visible_text"
> & {
  notes?: string | null;
};
export type EvidenceBundle = Defaults<
  Schemas["EvidenceBundle"],
  "browser_screenshots" | "commits" | "collected_at" | "documentation" | "repositories" | "warnings"
>;
export type EvidenceReference = Schemas["EvidenceReference"];
export type DocumentationEditResult = Defaults<
  Schemas["DocumentationEditResult"],
  "changed_docs" | "created_docs" | "updated_docs" | "warnings"
>;
export type DocumentationUpdate = Omit<
  Defaults<
    Schemas["DocumentationUpdate"],
    "risks_or_limitations" | "suggested_improvements"
  >,
  "documentation_edit"
> & {
  documentation_edit?: DocumentationEditResult | null;
};
export type ProviderRunMetadata = Schemas["ProviderRunMetadata"];
export type ValidationFinding = Defaults<Schemas["ValidationFinding"], "artifact_refs" | "evidence_refs">;
export type GuideSyncRunResult = Omit<
  Defaults<Schemas["GuideSyncRunResult"], "artifacts" | "findings">,
  "evidence" | "findings" | "request" | "update"
> & {
  evidence: EvidenceBundle;
  findings: ValidationFinding[];
  request: Omit<Schemas["GuideSyncRunRequest-Output"], "effective_model_configuration" | "requested_model_settings"> & {
    effective_model_configuration?: EffectiveModelConfiguration | null;
    requested_model_settings?: RequestedModelSettings | null;
  };
  update: DocumentationUpdate | null;
};

export type KnowledgeIndexSummary = Defaults<
  Schemas["KnowledgeIndexSummary"],
  "changed_documentation_files" | "warnings"
>;
export type KnowledgeIndexRun = Omit<Defaults<Present<Schemas["KnowledgeIndexRun"], "id">, "summary">, "summary"> & {
  summary: KnowledgeIndexSummary;
};
export type KnowledgeDocumentRef = Defaults<
  Present<Schemas["KnowledgeDocumentRef"], "content_hash" | "project_id" | "repo" | "source_commit">,
  "categories" | "concepts" | "extracted_names" | "keyphrases" | "search_terms" | "tags"
>;
export type KnowledgeSectionRef = Defaults<
  Present<
    Schemas["KnowledgeSectionRef"],
    "content_hash" | "end_line" | "project_id" | "repo" | "source_commit" | "start_line"
  >,
  "categories" | "concepts" | "extracted_names" | "keyphrases" | "search_terms" | "tags"
>;
export type KnowledgeDocumentRefs = Omit<Schemas["KnowledgeDocumentRefs"], "documents" | "sections"> & {
  documents: KnowledgeDocumentRef[];
  sections: KnowledgeSectionRef[];
};
export type KnowledgeDocumentDetail = Omit<
  Defaults<Schemas["KnowledgeDocumentDetail"], "sections" | "warnings">,
  "document" | "sections"
> & {
  document: KnowledgeDocumentRef;
  sections: KnowledgeSectionRef[];
};
export type KnowledgeTag = Schemas["KnowledgeTag"];
export type KnowledgeSearchScoreBreakdown = Schemas["KnowledgeSearchScoreBreakdown"];
export type KnowledgeSearchMatchedTerms = Defaults<
  Schemas["KnowledgeSearchMatchedTerms"],
  | "categories"
  | "components"
  | "concepts"
  | "documentation_areas"
  | "extracted_names"
  | "keyphrases"
  | "tags"
  | "workflows"
>;
export type KnowledgeSearchGraphReason = Schemas["KnowledgeSearchGraphReason"];
export type KnowledgeNode = Present<
  Schemas["KnowledgeNode"],
  "content_hash" | "created_at" | "end_line" | "metadata" | "path" | "project_id" | "repo" | "start_line"
>;
export type KnowledgeSearchDiagnostics = Omit<
  Defaults<Schemas["KnowledgeSearchDiagnostics"], "graph_reasons" | "matched_terms" | "score_breakdown" | "warnings">,
  "matched_terms" | "score_breakdown"
> & {
  matched_terms: KnowledgeSearchMatchedTerms;
  score_breakdown: KnowledgeSearchScoreBreakdown;
};
export type KnowledgeSearchResult = Omit<
  Defaults<Schemas["KnowledgeSearchResult"], "diagnostics">,
  "diagnostics" | "node"
> & {
  diagnostics: KnowledgeSearchDiagnostics;
  node: KnowledgeNode;
};

export type BranchInfo = Schemas["RepositoryBranch"];
export type BranchListResponse = Defaults<Schemas["BranchListResponse"], "branches">;
