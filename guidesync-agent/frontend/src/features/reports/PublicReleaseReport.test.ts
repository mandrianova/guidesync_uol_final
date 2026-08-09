import { describe, expect, it } from "vitest";

import { publicReportUrl } from "../../api/client";
import {
  hasPublicationReport,
  publicationReportAction
} from "../../components/ArtifactActions";
import { safePublicationUrl } from "../../components/PublicMarkdown";
import type {
  BrowserScreenshotEvidence,
  PublicationChange,
  PublicationScreenshotRef
} from "../../types";
import {
  screenshotArtifactLinks,
  screenshotStatusColor
} from "./ScreenshotEvidenceCard";
import {
  changeStoryClassName,
  publicationScreenshots,
  publicReportLabels
} from "./PublicReleaseReport";

describe("public release report helpers", () => {
  it("builds the React public route instead of an HTML artifact URL", () => {
    expect(publicReportUrl("run/with spaces")).toBe(
      "#/reports/run%2Fwith%20spaces/public"
    );
    expect(publicReportUrl("run-1", true)).toBe("#/reports/run-1/public?print=1");
  });

  it("shows the public action only for a persisted publication report", () => {
    const publication = { "report.json": "s3://reports/run-1/report.json" };
    const legacy = { "run.json": "s3://reports/run-1/run.json" };

    expect(hasPublicationReport(publication)).toBe(true);
    expect(hasPublicationReport(legacy)).toBe(false);
    expect(publicationReportAction("run-1", publication)).toEqual({
      disabled: false,
      href: "#/reports/run-1/public"
    });
    expect(publicationReportAction("run-1", legacy)).toEqual({
      disabled: true,
      href: null
    });
  });

  it("keeps the public report chrome in English", () => {
    expect(publicReportLabels().whyItMatters).toBe("Why it matters");
    expect(publicReportLabels().whereToFind).toBe("Where to find it");
  });

  it("shows every prepared screenshot for the same user-facing change", () => {
    const closed = {
      artifact_name: "menu-closed.png",
      scenario_id: "menu-closed"
    } as PublicationScreenshotRef;
    const open = {
      artifact_name: "menu-open.png",
      scenario_id: "menu-open"
    } as PublicationScreenshotRef;
    const change: PublicationChange = {
      id: "change-menu",
      claim_id: "claim-menu",
      title: "Menu update",
      summary: "The navigation state is clearer.",
      why_it_matters: "The current state is visible.",
      how_to_markdown: "",
      examples: [],
      evidence_refs: [],
      screenshot: null,
      screenshots: []
    };

    expect(publicationScreenshots({ ...change, screenshots: [closed, open] })).toEqual([
      closed,
      open
    ]);
    expect(publicationScreenshots({ ...change, screenshot: closed })).toEqual([closed]);
  });

  it("uses a split spotlight layout only when an image is visible", () => {
    expect(changeStoryClassName(true, false)).toBe(
      "public-change public-change-spotlight"
    );
    expect(changeStoryClassName(true, true)).toBe(
      "public-change public-change-spotlight public-change-with-evidence"
    );
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
