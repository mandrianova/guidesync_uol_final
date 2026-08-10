import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { publicReportUrl } from "../../api/client";
import {
  hasPublicationReport,
  publicationReportAction
} from "../../components/ArtifactActions";
import {
  PublicMarkdown,
  safePublicationUrl
} from "../../components/PublicMarkdown";
import type { BrowserScreenshotEvidence, PublicationReport } from "../../types";
import {
  screenshotArtifactLinks,
  screenshotStatusColor
} from "./ScreenshotEvidenceCard";
import {
  changeStoryClassName,
  PublicReleaseReport,
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
    expect(publicReportLabels().openProduct).toBe("Open product");
    expect(publicReportLabels().whyItMatters).toBe("Why it matters");
    expect(publicReportLabels().whereToFind).toBe("Where to find it");
  });

  it("renders the saved product action in the header and footer", () => {
    const report = {
      schema_version: "1.0",
      locale: "en",
      product_name: "Atlas",
      product_url: "https://example.com/product",
      title: "Atlas update",
      summary: "A concise release summary.",
      user_value: "The updated workflow is easier to use.",
      release_date: "2026-08-11",
      changes: [],
      call_to_action: "Try the updated workflow."
    } satisfies PublicationReport;

    const html = renderToStaticMarkup(
      createElement(PublicReleaseReport, { report, runId: "run-1" })
    );

    expect(html.match(/>Open product<\/a>/g)).toHaveLength(2);
    expect(html.match(/href="https:\/\/example.com\/product"/g)).toHaveLength(2);
    expect(html.match(/target="_blank"/g)).toHaveLength(2);
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

  it("preserves fenced code blocks in public guidance", () => {
    const html = renderToStaticMarkup(
      createElement(PublicMarkdown, {
        markdown: "```ts\nconst enabled = true;\n```"
      })
    );

    expect(html).toContain('<pre><code class="language-ts">');
    expect(html).toContain("const enabled = true;");
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
