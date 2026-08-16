import { describe, expect, it } from "vitest";

import { describeReportChangeScope } from "./reportScope";

describe("report change scope", () => {
  it("formats a shared date period", () => {
    expect(
      describeReportChangeScope({
        repositories: [
          {
            name: "web-app",
            since: "2026-08-01",
            until: "2026-08-09",
            branches: ["main"]
          }
        ]
      })
    ).toEqual({ label: "Change period", value: "1 Aug 2026 — 9 Aug 2026" });
  });

  it("groups selected branches by repository", () => {
    expect(
      describeReportChangeScope({
        repositories: [
          {
            name: "solutions-ui",
            since: null,
            until: null,
            branches: ["main", "billing-overhaul"]
          },
          {
            name: "functions",
            since: null,
            until: null,
            branches: ["release"]
          }
        ]
      })
    ).toEqual({
      label: "Branches",
      value: "solutions-ui: main, billing-overhaul; functions: release"
    });
  });
});
