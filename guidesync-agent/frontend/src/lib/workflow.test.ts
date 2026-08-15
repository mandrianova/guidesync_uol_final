import { describe, expect, it } from "vitest";

import type { ProjectWorkflowTask } from "../types";
import { activeWorkflowTaskStatus, workflowTaskResultSummary } from "./workflow";

describe("activeWorkflowTaskStatus", () => {
  it("keeps stoppable workflow states active", () => {
    expect(activeWorkflowTaskStatus("queued")).toBe(true);
    expect(activeWorkflowTaskStatus("running")).toBe(true);
    expect(activeWorkflowTaskStatus("retrying")).toBe(true);
    expect(activeWorkflowTaskStatus("blocked")).toBe(true);
    expect(activeWorkflowTaskStatus("completed")).toBe(false);
    expect(activeWorkflowTaskStatus("failed")).toBe(false);
    expect(activeWorkflowTaskStatus("cancelled")).toBe(false);
  });
});

describe("workflowTaskResultSummary", () => {
  it("returns a screenshot capture reason from the typed workflow result", () => {
    const task = {
      result: {
        summary: "The configured session redirected to the login origin."
      }
    } as ProjectWorkflowTask;

    expect(workflowTaskResultSummary(task)).toBe(
      "The configured session redirected to the login origin."
    );
  });

  it("ignores workflow results without a summary", () => {
    expect(workflowTaskResultSummary({ result: null } as ProjectWorkflowTask)).toBeNull();
  });
});
