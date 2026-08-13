import { describe, expect, it } from "vitest";

import { activeWorkflowTaskStatus } from "./workflow";

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
