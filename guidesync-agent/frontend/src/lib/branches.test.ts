import { describe, expect, it } from "vitest";

import { retryableReportStatus } from "./branches";

describe("report status helpers", () => {
  it("allows retry only for unsuccessful terminal reports", () => {
    expect(retryableReportStatus("failed")).toBe(true);
    expect(retryableReportStatus("partial_failure")).toBe(true);
    expect(retryableReportStatus("completed")).toBe(false);
    expect(retryableReportStatus("running")).toBe(false);
    expect(retryableReportStatus("cancelled")).toBe(false);
  });
});
