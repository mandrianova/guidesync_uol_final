import {
  IconArrowLeft,
  IconDownload,
  IconExternalLink,
  IconPrinter,
  IconRefresh
} from "@tabler/icons-react";
import { useState } from "react";

import { artifactUrl } from "../../api/client";
import { PublicMarkdown } from "../../components/PublicMarkdown";
import {
  isVideoActiveStatus,
  isVideoRegeneration,
  videoActionLabel
} from "../../lib/videoPresentation";
import type {
  PublicationChange,
  PublicationReport,
  VideoPresentationSummary
} from "../../types";

interface PublicReleaseReportProps {
  report: PublicationReport;
  runId: string;
  videoPresentation?: VideoPresentationSummary | null;
  videoActionError?: string | null;
  videoActionLoading?: boolean;
  onVideoAction?: (regenerate: boolean) => void;
}

export function PublicReleaseReport({
  report,
  runId,
  videoPresentation,
  videoActionError,
  videoActionLoading = false,
  onVideoAction
}: PublicReleaseReportProps) {
  const [failedImages, setFailedImages] = useState<Set<string>>(new Set());
  const labels = publicReportLabels();
  const spotlight =
    report.changes.find((change) => change.id === report.spotlight_change_id) ||
    report.changes[0];
  const supporting = report.changes.filter((change) => change.id !== spotlight?.id);
  const videoStatus = videoPresentation?.status || "disabled";
  const videoArtifact = videoPresentation?.video_artifact_name || null;
  const videoActive = isVideoActiveStatus(videoStatus);
  const regenerate = isVideoRegeneration(videoStatus, Boolean(videoArtifact));

  const hideImage = (artifactName: string) => {
    setFailedImages((current) => new Set(current).add(artifactName));
  };

  return (
    <main className="public-release" lang="en">
      <article className="public-release-sheet">
        <header className="public-release-hero">
          <div className="public-release-masthead">
            <a className="public-release-back" href="#/reports">
              <IconArrowLeft aria-hidden size={16} />
              {labels.back}
            </a>
            <div className="public-release-masthead-actions">
              <ProductAction
                href={report.product_url}
                label={labels.openProduct}
                masthead
              />
              <button
                className="public-release-print public-release-print-masthead"
                onClick={() => window.print()}
                type="button"
              >
                <IconPrinter aria-hidden size={16} />
                {labels.print}
              </button>
            </div>
          </div>
          <p className="public-release-kicker">{labels.kicker}</p>
          <h1>{publicReportHeading(report.product_name, report.release_date)}</h1>
          <div className="public-release-hero-grid">
            <p className="public-release-summary">{report.summary}</p>
            <aside className="public-release-value" aria-label={labels.whyItMatters}>
              <span>{labels.whyItMatters}</span>
              <p>{report.user_value}</p>
              {report.release_period ? <small>{report.release_period}</small> : null}
            </aside>
          </div>
        </header>

        {spotlight ? (
          <ChangeStory
            change={spotlight}
            failedImages={failedImages}
            hideImage={hideImage}
            labels={labels}
            runId={runId}
            spotlight
          />
        ) : null}

        {supporting.length ? (
          <section className="public-release-supporting">
            <div className="public-release-section-heading">
              <p>{labels.alsoChanged}</p>
              <h2>{labels.moreImprovements}</h2>
            </div>
            <div className="public-release-supporting-grid">
              {supporting.map((change) => (
                <ChangeStory
                  change={change}
                  failedImages={failedImages}
                  hideImage={hideImage}
                  key={change.id}
                  labels={labels}
                  runId={runId}
                />
              ))}
            </div>
          </section>
        ) : null}

        <section className="public-release-video" aria-labelledby="release-video-title">
          <div className="public-release-section-heading">
            <p>{labels.videoKicker}</p>
            <h2 id="release-video-title">{labels.videoTitle}</h2>
          </div>
          {videoArtifact ? (
            <>
              <video
                controls
                playsInline
                preload="metadata"
                src={artifactUrl(runId, videoArtifact)}
              />
              <div className="public-release-video-links">
                <a
                  className="public-release-transcript"
                  download
                  href={artifactUrl(runId, videoArtifact)}
                >
                  <IconDownload aria-hidden size={17} />
                  {labels.downloadVideo}
                </a>
                {videoPresentation?.transcript_artifact_name ? (
                  <a
                    className="public-release-transcript"
                    download
                    href={artifactUrl(runId, videoPresentation.transcript_artifact_name)}
                  >
                    <IconDownload aria-hidden size={17} />
                    {labels.downloadTranscript}
                  </a>
                ) : null}
              </div>
            </>
          ) : (
            <p className="public-release-video-copy">{labels.videoDescription}</p>
          )}
          {videoActive ? (
            <p className="public-release-video-status">{labels.videoInProgress}</p>
          ) : videoStatus === "failed" ? (
            <p className="public-release-video-error">{labels.videoFailed}</p>
          ) : null}
          {videoActionError ? (
            <p className="public-release-video-error">{videoActionError}</p>
          ) : null}
          {onVideoAction ? (
            <button
              className="public-release-video-action"
              disabled={videoActive || videoActionLoading}
              onClick={() => onVideoAction(regenerate)}
              type="button"
            >
              <IconRefresh aria-hidden size={17} />
              {videoActionLabel(videoStatus, Boolean(videoArtifact), videoActionLoading)}
            </button>
          ) : null}
        </section>

        <footer
          className={
            report.product_url
              ? "public-release-footer"
              : "public-release-footer public-release-footer-actions-only"
          }
        >
          {report.product_url ? (
            <div>
              <p className="public-release-kicker">{labels.nextStep}</p>
              <h2>{report.call_to_action}</h2>
            </div>
          ) : null}
          <div className="public-release-footer-actions">
            <ProductAction href={report.product_url} label={labels.openProduct} />
            <button className="public-release-print" onClick={() => window.print()} type="button">
              <IconPrinter aria-hidden size={18} />
              {labels.print}
            </button>
          </div>
        </footer>
      </article>
    </main>
  );
}

interface ProductActionProps {
  href?: string | null;
  label: string;
  masthead?: boolean;
}

function ProductAction({ href, label, masthead = false }: ProductActionProps) {
  if (!href) {
    return null;
  }
  const className = [
    "public-release-product-link",
    masthead ? "public-release-product-link-masthead" : ""
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <a className={className} href={href} rel="noreferrer" target="_blank">
      <IconExternalLink aria-hidden size={masthead ? 16 : 18} />
      {label}
    </a>
  );
}

interface ChangeStoryProps {
  change: PublicationChange;
  failedImages: Set<string>;
  hideImage: (artifactName: string) => void;
  labels: ReturnType<typeof publicReportLabels>;
  runId: string;
  spotlight?: boolean;
}

function ChangeStory({
  change,
  failedImages,
  hideImage,
  labels,
  runId,
  spotlight = false
}: ChangeStoryProps) {
  const visibleScreenshots = change.screenshots.filter(
    (screenshot) => !failedImages.has(screenshot.artifact_name)
  );
  const storyClassName = changeStoryClassName(spotlight, visibleScreenshots.length > 0);
  return (
    <section className={storyClassName}>
      <div className="public-change-copy">
        <p className="public-release-kicker">{spotlight ? labels.spotlight : labels.change}</p>
        <h2>{change.title}</h2>
        <p className="public-change-summary">{change.summary}</p>
        <div className="public-change-impact">
          <span>{labels.whatItMeans}</span>
          <p>{change.why_it_matters}</p>
        </div>
        {change.how_to_markdown ? (
          <div className="public-change-howto">
            <h3>{labels.howTo}</h3>
            <PublicMarkdown markdown={change.how_to_markdown} />
          </div>
        ) : null}
        {change.examples.length ? (
          <div className="public-change-examples">
            <h3>{labels.examples}</h3>
            <ul>
              {change.examples.map((example) => (
                <li key={example}>{example}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
      {visibleScreenshots.length ? (
        <div className="public-change-evidence-gallery">
          {visibleScreenshots.map((screenshot, index) => (
            <figure className="public-change-evidence" key={screenshot.scenario_id}>
              <div className="public-change-evidence-label">{labels.whereToFind}</div>
              <img
                alt={screenshot.alt_text}
                height={screenshot.height || undefined}
                loading={spotlight && index === 0 ? "eager" : "lazy"}
                onError={() => hideImage(screenshot.artifact_name)}
                src={artifactUrl(runId, screenshot.artifact_name)}
                width={screenshot.width || undefined}
              />
              <figcaption>{screenshot.caption}</figcaption>
            </figure>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function changeStoryClassName(spotlight: boolean, hasEvidence: boolean) {
  return [
    "public-change",
    spotlight ? "public-change-spotlight" : "",
    hasEvidence ? "public-change-with-evidence" : ""
  ]
    .filter(Boolean)
    .join(" ");
}

export function publicReportLabels() {
  return {
    alsoChanged: "Additional changes",
    back: "Back to GuideSync reports",
    change: "Change",
    examples: "Examples",
    howTo: "How to use it",
    kicker: "Release notes",
    moreImprovements: "Other changes",
    nextStep: "Next step",
    openProduct: "Open product",
    print: "Save / print PDF",
    spotlight: "Change",
    whereToFind: "Where to find it",
    whatItMeans: "What this means",
    whyItMatters: "User impact",
    videoKicker: "Video presentation",
    videoTitle: "Watch the release overview",
    downloadTranscript: "Download narration transcript",
    downloadVideo: "Download video",
    videoDescription: "Create a narrated video overview when you are ready to share this report.",
    videoFailed: "Video generation did not finish. The report is still available.",
    videoInProgress: "A video is being generated. You can keep reading or leave this page."
  };
}

export function publicReportHeading(
  productName: string,
  releaseDate?: string | null
): string {
  const name = productName.trim();
  const date = releaseDate ? formatReleaseDate(releaseDate) : "";
  return [name, date].filter(Boolean).join(" — ");
}

function formatReleaseDate(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "long",
    timeZone: "UTC"
  }).format(new Date(`${value}T00:00:00Z`));
}
