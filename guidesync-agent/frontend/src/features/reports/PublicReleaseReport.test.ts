import { MantineProvider } from "@mantine/core";
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

  it("shows selected branches in the public report", () => {
    const report = {
      schema_version: "1.0",
      locale: "en",
      product_name: "Atlas",
      title: "Atlas release notes",
      summary: "A concise release summary.",
      user_value: "The updated workflow is easier to use.",
      release_date: "2026-08-11",
      change_scope: {
        repositories: [
          {
            name: "web-app",
            since: null,
            until: null,
            branches: ["main", "billing-overhaul"]
          }
        ]
      },
      changes: [],
      call_to_action: "Try the updated workflow."
    } satisfies PublicationReport;

    const html = renderToStaticMarkup(
      createElement(PublicReleaseReport, { report, runId: "run-1" })
    );

    expect(html).toContain("Branches: web-app: main, billing-overhaul");
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

  it("shows video links and explicit regeneration for a completed video", () => {
    const report = {
      schema_version: "1.0",
      locale: "en",
      product_name: "Atlas",
      title: "Atlas release notes",
      summary: "A concise release summary.",
      user_value: "The updated workflow is easier to use.",
      release_date: "2026-08-11",
      changes: [],
      call_to_action: "Try the updated workflow."
    } satisfies PublicationReport;

    const html = renderToStaticMarkup(
      createElement(PublicReleaseReport, {
        report,
        runId: "run-1",
        onVideoAction: () => undefined,
        videoPresentation: {
          policy: "optional",
          status: "completed",
          video_artifact_name: "video-presentation.mp4",
          transcript_artifact_name: "video-presentation-transcript.txt"
        }
      })
    );

    expect(html).toContain("<video");
    expect(html).toContain("/runs/run-1/artifacts/video-presentation.mp4");
    expect(html).toContain("Download video");
    expect(html).toContain("Download narration transcript");
    expect(html).toContain("Regenerate video");
  });

  it("offers generation for a ready report without a video", () => {
    const report = {
      schema_version: "1.0",
      locale: "en",
      product_name: "Atlas",
      title: "Atlas release notes",
      summary: "A concise release summary.",
      user_value: "The updated workflow is easier to use.",
      release_date: "2026-08-11",
      changes: [],
      call_to_action: "Try the updated workflow."
    } satisfies PublicationReport;

    const html = renderToStaticMarkup(
      createElement(PublicReleaseReport, {
        report,
        runId: "run-1",
        onVideoAction: () => undefined,
        videoPresentation: { policy: "disabled", status: "disabled" }
      })
    );

    expect(html).toContain("Generate video");
    expect(html).not.toContain("<video");
  });

  it("uses a split spotlight layout only when an image is visible", () => {
    expect(changeStoryClassName(true, false)).toBe(
      "public-change public-change-spotlight"
    );
    expect(changeStoryClassName(true, true)).toBe(
      "public-change public-change-spotlight public-change-with-evidence"
    );
  });

  it("offers a full-size preview and the original screenshot artifact", () => {
    const report = {
      schema_version: "1.0",
      locale: "en",
      product_name: "Atlas",
      title: "Atlas release notes",
      summary: "A concise release summary.",
      user_value: "The updated workflow is easier to use.",
      release_date: "2026-08-16",
      changes: [
        {
          id: "change-1",
          claim_id: "claim-1",
          title: "Clearer usage details",
          summary: "Usage is easier to inspect.",
          why_it_matters: "People can understand their limits.",
          how_to_markdown: "",
          examples: [],
          evidence_refs: [],
          screenshots: [
            {
              scenario_id: "scenario-1",
              artifact_name: "prepared-shot.png",
              caption: "Usage details",
              alt_text: "Usage details panel",
              width: 1440,
              height: 900
            }
          ]
        }
      ],
      call_to_action: "Try the updated workflow."
    } satisfies PublicationReport;

    const html = renderToStaticMarkup(
      createElement(
        MantineProvider,
        null,
        createElement(PublicReleaseReport, { report, runId: "run-1" })
      )
    );

    expect(html).toContain(
      'aria-label="Open full-size preview: Usage details panel"'
    );
    expect(html).toContain("Open preview");
    expect(html).toContain("/runs/run-1/artifacts/prepared-shot.png");
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
      derivative_artifact_name: "capture-derivative.png",
      edit_manifest_artifact_name: "capture-edits.json",
      validation_status: "passed"
    } as BrowserScreenshotEvidence;

    expect(
      screenshotArtifactLinks(
        "run-1",
        {
          "capture-prepared.png": "/worker/private/prepared.png",
          "capture-raw.png": "/worker/private/raw.png",
          "capture-derivative.png": "/worker/private/derivative.png",
          "capture-edits.json": "/worker/private/edits.json"
        },
        screenshot
      )
    ).toEqual({
      derivative: "/runs/run-1/artifacts/capture-derivative.png",
      manifest: "/runs/run-1/artifacts/capture-edits.json",
      prepared: "/runs/run-1/artifacts/capture-prepared.png",
      raw: "/runs/run-1/artifacts/capture-raw.png"
    });
    expect(screenshotStatusColor(screenshot.validation_status)).toBe("teal");
  });
});
