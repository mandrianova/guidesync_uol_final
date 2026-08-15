import type { ProjectWorkflowTask, ProjectWorkflowTaskStatus } from "../types";

export function activeWorkflowTaskStatus(status: ProjectWorkflowTaskStatus): boolean {
  return status === "queued" || status === "running" || status === "retrying" || status === "blocked";
}

export function workflowTaskResultSummary(task: ProjectWorkflowTask): string | null {
  if (!task.result || typeof task.result !== "object" || !("summary" in task.result)) {
    return null;
  }
  return typeof task.result.summary === "string" && task.result.summary.trim()
    ? task.result.summary
    : null;
}
