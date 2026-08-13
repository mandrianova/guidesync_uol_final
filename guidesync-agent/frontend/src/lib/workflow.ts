import type { ProjectWorkflowTaskStatus } from "../types";

export function activeWorkflowTaskStatus(status: ProjectWorkflowTaskStatus): boolean {
  return status === "queued" || status === "running" || status === "retrying" || status === "blocked";
}
