import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { publicReportUrl } from "../../api/client";
import { publicationReportAction } from "../../components/ArtifactActions";
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
  publicReportHeading,
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
    expect(publicationReportAction("run-1", true)).toEqual({
      disabled: false,
      href: "#/reports/run-1/public"
    });
    expect(publicationReportAction("run-1", false)).toEqual({
      disabled: true,
      href: null
    });
  });

  it("keeps the public report chrome in English", () => {
    expect(publicReportLabels().openProduct).toBe("Open product");
    expect(publicReportLabels().whyItMatters).toBe("User impact");
    expect(publicReportLabels().whereToFind).toBe("Where to find it");
  });

  it("builds a neutral heading from the product and release date", () => {
    expect(publicReportHeading("Atlas", "2026-08-11")).toBe(
      "Atlas — 11 August 2026"
    );
    expect(publicReportHeading("Atlas", null)).toBe("Atlas");
  });

  it("renders the saved product action in the header and footer", () => {
    const report = {
      schema_version: "1.0",
      locale: "en",
      product_name: "Atlas",
      product_url: "https://example.com/product",
      title: "A wildly important and unprecedented update",
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
    expect(html).toContain("Atlas — 11 August 2026");
    expect(html).not.toContain("wildly important");
  });

  it("omits the product call to action when there is no product URL", () => {
    const report = {
      schema_version: "1.0",
      locale: "en",
      product_name: "Atlas",
      product_url: null,
      title: "Internal run title",
      summary: "A concise release summary.",
      user_value: "The updated workflow is easier to use.",
      release_date: "2026-08-11",
      changes: [],
      call_to_action: "Open the product and try the updated workflow."
    } satisfies PublicationReport;

    const html = renderToStaticMarkup(
      createElement(PublicReleaseReport, { report, runId: "run-1" })
    );

    expect(html).not.toContain(report.call_to_action);
    expect(html).toContain("public-release-footer-actions-only");
    expect(html.match(/>Save \/ print PDF<\/button>/g)).toHaveLength(2);
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
