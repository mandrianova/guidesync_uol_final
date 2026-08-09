import { describe, expect, it } from "vitest";

import { publicReportUrl } from "../../api/client";
import { hasPublicationReport } from "../../components/ArtifactActions";
import { safePublicationUrl } from "../../components/PublicMarkdown";
import type { BrowserScreenshotEvidence } from "../../types";
import {
  screenshotArtifactLinks,
  screenshotStatusColor
} from "./ScreenshotEvidenceCard";
import { publicReportLabels } from "./PublicReleaseReport";

describe("public release report helpers", () => {
  it("builds the React public route instead of an HTML artifact URL", () => {
    expect(publicReportUrl("run/with spaces")).toBe(
      "#/reports/run%2Fwith%20spaces/public"
    );
    expect(publicReportUrl("run-1", true)).toBe("#/reports/run-1/public?print=1");
  });

  it("shows the public action only for a persisted publication report", () => {
    expect(
      hasPublicationReport({ "report.json": "s3://reports/run-1/report.json" })
    ).toBe(true);
    expect(hasPublicationReport({ "run.json": "s3://reports/run-1/run.json" })).toBe(
      false
    );
  });

  it("keeps labels in the selected locale", () => {
    expect(publicReportLabels("en").whyItMatters).toBe("Why it matters");
    expect(publicReportLabels("ru").whyItMatters).toBe("Почему это важно");
  });

  it("rejects unsafe or insecure Markdown links", () => {
    expect(safePublicationUrl("javascript:alert(1)")).toBeNull();
    expect(safePublicationUrl("http://example.com/private")).toBeNull();
    expect(safePublicationUrl("//example.com/private")).toBeNull();
    expect(safePublicationUrl("/\\example.com/private")).toBeNull();
    expect(safePublicationUrl("https://user:secret@example.com/private")).toBeNull();
    expect(safePublicationUrl("https://example.com/guide")).toBe(
      "https://example.com/guide"
    );
    expect(safePublicationUrl("/settings")).toBe("/settings");
    expect(safePublicationUrl("#details")).toBe("#details");
  });

  it("links internal screenshot inspection to durable prepared and raw artifacts", () => {
    const screenshot = {
      path: "/worker/private/prepared.png",
      prepared_artifact_name: "capture-prepared.png",
      raw_artifact_name: "capture-raw.png",
      validation_status: "passed"
    } as BrowserScreenshotEvidence;

    expect(
      screenshotArtifactLinks(
        "run-1",
        {
          "capture-prepared.png": "/worker/private/prepared.png",
          "capture-raw.png": "/worker/private/raw.png"
        },
        screenshot
      )
    ).toEqual({
      prepared: "/runs/run-1/artifacts/capture-prepared.png",
      raw: "/runs/run-1/artifacts/capture-raw.png"
    });
    expect(screenshotStatusColor(screenshot.validation_status)).toBe("teal");
  });
});
