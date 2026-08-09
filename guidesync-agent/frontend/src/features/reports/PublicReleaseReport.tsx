import { IconArrowLeft, IconPrinter } from "@tabler/icons-react";
import { useState } from "react";

import { artifactUrl } from "../../api/client";
import { PublicMarkdown } from "../../components/PublicMarkdown";
import type {
  PublicationChange,
  PublicationReport,
  ReportLocale
} from "../../types";

interface PublicReleaseReportProps {
  report: PublicationReport;
  runId: string;
}

export function PublicReleaseReport({ report, runId }: PublicReleaseReportProps) {
  const [failedImages, setFailedImages] = useState<Set<string>>(new Set());
  const labels = publicReportLabels(report.locale);
  const spotlight =
    report.changes.find((change) => change.id === report.spotlight_change_id) ||
    report.changes[0];
  const supporting = report.changes.filter((change) => change.id !== spotlight?.id);

  const hideImage = (artifactName: string) => {
    setFailedImages((current) => new Set(current).add(artifactName));
  };

  return (
    <main className="public-release" lang={report.locale}>
      <article className="public-release-sheet">
        <header className="public-release-hero">
          <div className="public-release-masthead">
            <a className="public-release-back" href="#/reports">
              <IconArrowLeft aria-hidden size={16} />
              {labels.back}
            </a>
            <span className="public-release-product">{report.product_name}</span>
            <div className="public-release-masthead-actions">
              <span className="public-release-date">
                {formatReleaseDate(report.release_date, report.locale)}
              </span>
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
          <div className="public-release-hero-grid">
            <div>
              <p className="public-release-kicker">{labels.kicker}</p>
              <h1>{report.title}</h1>
              <p className="public-release-summary">{report.summary}</p>
            </div>
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

        <footer className="public-release-footer">
          <div>
            <p className="public-release-kicker">{labels.nextStep}</p>
            <h2>{report.call_to_action}</h2>
          </div>
          <button className="public-release-print" onClick={() => window.print()} type="button">
            <IconPrinter aria-hidden size={18} />
            {labels.print}
          </button>
        </footer>
      </article>
    </main>
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
  const screenshots = publicationScreenshots(change);
  const visibleScreenshots = screenshots.filter(
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

export function publicationScreenshots(change: PublicationChange) {
  if (change.screenshots.length) {
    return change.screenshots;
  }
  return change.screenshot ? [change.screenshot] : [];
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

export function publicReportLabels(locale: ReportLocale) {
  if (locale === "ru") {
    return {
      alsoChanged: "Другие изменения",
      back: "К отчётам GuideSync",
      change: "Изменение",
      examples: "Примеры",
      howTo: "Как использовать",
      kicker: "Обновление продукта",
      moreImprovements: "Дополнительные улучшения",
      nextStep: "Следующий шаг",
      print: "Сохранить / печать PDF",
      spotlight: "Главное изменение",
      whereToFind: "Где найти",
      whatItMeans: "Что это даёт",
      whyItMatters: "Почему это важно"
    };
  }
  return {
    alsoChanged: "Also changed",
    back: "Back to GuideSync reports",
    change: "Change",
    examples: "Examples",
    howTo: "How to use it",
    kicker: "Product update",
    moreImprovements: "More improvements",
    nextStep: "Next step",
    print: "Save / print PDF",
    spotlight: "Spotlight change",
    whereToFind: "Where to find it",
    whatItMeans: "What this means",
    whyItMatters: "Why it matters"
  };
}

function formatReleaseDate(value: string, locale: ReportLocale): string {
  return new Intl.DateTimeFormat(locale === "ru" ? "ru-RU" : "en-GB", {
    dateStyle: "long",
    timeZone: "UTC"
  }).format(new Date(`${value}T00:00:00Z`));
}
